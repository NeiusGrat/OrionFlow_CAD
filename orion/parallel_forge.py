"""Parallel batched forge (Phase-X W6) — production generation infrastructure.

One producer, N FreeCAD workers. The producer samples blueprints, splits each
batch across the workers, launches them concurrently, then verifies results and
writes them — it is the SOLE writer to SQLite, so there is no cross-process
write contention and `INSERT OR REPLACE` on the (blueprint_hash, status) key
makes duplicate writes idempotent rather than corrupting. Each worker builds
its whole slice in one FreeCAD process (startup amortized -> throughput).

Resumable exactly like forge_loop: `--target` tops the corpus up to N clean
records, seed advances from the current DB count, and the batch loop stops when
the DB reaches target. A per-worker watchdog kills a slice that exceeds its
build-time budget (OCC hang) and keeps every completed job in that slice.

Usage:
    python -m orion.parallel_forge --db data/forge/corpus_v2.db \
        --target 5000 --workers 8 --batch 240
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time

from . import corpus_db
from .blueprint import Blueprint, BlueprintError
from .expr import ExprError
from .forge import (BUILD_TIMEOUT_S, _freecad_python,
                    check_assertions, failed_preconditions)
from .forge_loop import FAULT_P, STRESS_RATE, _clean_count, _refreeze
from .profiles import ProfileError
from .sampler import TopologySampler


def _needs_mesh(bp: Blueprint) -> bool:
    return any(a.get("kind") == "body_mesh_converged" for a in bp.assertions)


def _safe_resolve(bp: Blueprint):
    """Resolve a frozen blueprint to a graph, or None when a profile builder
    rejects the geometry. A blueprint can pass the static freeze check yet be
    geometrically infeasible (e.g. a bolt circle whose holes overlap) — that
    surfaces only here, and is treated as an infeasible draw, not a crash."""
    try:
        return bp.resolve()
    except (ProfileError, ExprError, BlueprintError, ValueError):
        return None


def _verdict(bp: Blueprint, result: dict, forced: bool) -> dict:
    """Reconstruct a run_blueprint-style verdict from a worker measurement."""
    if not result or not result.get("ok"):
        return {"passed": False, "build_ok": False, "assertions": [],
                "build_log": {"error": (result or {}).get("error", "no result")},
                "measured": {}}
    measured = result["measured"]
    build_report = measured.pop("build_report", {})
    rows = check_assertions(bp, measured)
    passed = bool(rows) and all(r["passed"] for r in rows) and not forced
    return {"passed": passed, "build_ok": bool(measured),
            "assertions": rows, "measured": measured,
            "build_log": {"build_report": build_report}}


class _Job:
    __slots__ = ("tag", "kind", "bp", "graph", "meta", "fault", "trace",
                 "mesh")

    def __init__(self, tag, kind, bp, graph, meta, fault=None, trace=None):
        self.tag = tag
        self.kind = kind          # clean | stress | injected
        self.bp = bp
        self.graph = graph
        self.meta = meta
        self.fault = fault
        self.trace = trace
        self.mesh = _needs_mesh(bp)


def _run_batch(jobs, workers, scratch):
    """Build every job across ``workers`` concurrent FreeCAD processes.
    Returns {tag: result_dict}. A worker that overruns its budget is killed;
    its completed job files are still collected."""
    gdir = os.path.join(scratch, "graphs")
    rdir = os.path.join(scratch, "results")
    mdir = os.path.join(scratch, "manifests")
    sdir = os.path.join(scratch, "fcstd")
    for d in (gdir, rdir, mdir, sdir):
        os.makedirs(d, exist_ok=True)

    manifest_entries = []
    for j in jobs:
        gp = os.path.join(gdir, f"{j.tag}.json")
        with open(gp, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in j.graph.items() if k != "_analysis"}, fh)
        manifest_entries.append({"graph_path": gp, "tag": j.tag,
                                 "mesh_body": j.mesh})

    # slice round-robin so mesh (slow) jobs spread across workers
    slices = [manifest_entries[i::workers] for i in range(workers)]
    py = _freecad_python()
    here = os.path.dirname(os.path.abspath(__file__))
    worker = os.path.join(here, "fc_batch_worker.py")
    procs = []
    for wi, sl in enumerate(slices):
        if not sl:
            continue
        mpath = os.path.join(mdir, f"w{wi}.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(sl, fh)
        p = subprocess.Popen(
            [py, worker, "--manifest", mpath, "--out-dir", rdir,
             "--scratch", sdir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # budget: per-job timeout x slice length, with headroom + a floor
        budget = max(120, int(BUILD_TIMEOUT_S * len(sl) * 1.2))
        procs.append((p, time.time() + budget))

    for p, deadline in procs:
        while p.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if p.poll() is None:            # overran budget — OCC hang in the slice
            p.kill()
            try:
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass

    results = {}
    for j in jobs:
        rp = os.path.join(rdir, f"{j.tag}.json")
        if os.path.exists(rp):
            try:
                results[j.tag] = json.load(open(rp, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                results[j.tag] = {"tag": j.tag, "ok": False,
                                  "error": "unreadable result"}
        else:
            results[j.tag] = {"tag": j.tag, "ok": False,
                              "error": "no result (worker killed / timeout)"}
    # clear per-batch scratch to bound disk
    for d in (gdir, rdir, mdir, sdir):
        shutil.rmtree(d, ignore_errors=True)
    return results


def run(db_path: str, target: int, seed: int, workers: int, batch: int,
        out_dir: str) -> dict:
    already = _clean_count(db_path)
    sampler = TopologySampler(seed=seed + already)
    con = corpus_db.connect(db_path)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="orion_pforge_")

    stats = {"target": target, "start_clean": already, "passed": 0,
             "stress": 0, "injected": 0, "faults_caught": 0,
             "build_failed": 0, "batches": 0, "worker_slices": 0}
    written = 0
    t0 = time.time()

    def _save(payload, status):
        nonlocal written
        corpus_db.insert(con, payload, status)
        written += 1
        if written % 50 == 0:
            con.commit()

    # Progress is measured by THIS run's accepted cleans on top of the count
    # at start; _clean_count already includes our committed rows, so summing
    # the two would double-count and stop early.
    while already + stats["passed"] < target:
        # ---- sample a batch of jobs ------------------------------------- #
        jobs, i = [], 0
        remaining = target - (already + stats["passed"])
        want = min(batch, max(1, remaining))
        while sum(1 for j in jobs if j.kind == "clean") < want:
            draw = sampler.draw()
            if draw is None:
                break
            bp, faults, seq, recipe, meta = draw
            i += 1
            tag = f"b{stats['batches']}_{i}_{recipe}"

            clean_graph = _safe_resolve(bp)
            if clean_graph is None:
                continue                       # infeasible geometry — reroll

            if faults and sampler.rng.random() < STRESS_RATE:
                fname = sampler.rng.choice(list(faults))
                mutate, fmeta = faults[fname]
                try:
                    sbp = _refreeze(bp, mutate)
                except (BlueprintError, ValueError):
                    continue
                sgraph = _safe_resolve(sbp)
                if sgraph is None:
                    continue
                jobs.append(_Job(tag + "_stress", "stress", sbp, sgraph,
                                 meta, fname,
                                 {"source": "stress_natural", "fault": fname,
                                  **fmeta}))
                continue

            jobs.append(_Job(tag, "clean", bp, clean_graph, meta))
            # count this signature against its per-signature clean cap now, at
            # queue time, so the cap holds within the batch (accept() only runs
            # after the whole batch builds).
            sampler.note_clean(meta["feature_sequence_hash"])
            # injected fault decided at draw time; kept only if clean passes
            if faults and sampler.rng.random() < FAULT_P:
                fname = sampler.rng.choice(list(faults))
                mutate, fmeta = faults[fname]
                try:
                    fbp = _refreeze(bp, mutate)
                except (BlueprintError, ValueError):
                    continue
                pre = failed_preconditions(fbp)
                if pre:
                    # caught pre-build: no worker job, finalize immediately
                    jobs.append(_Job(tag + "_inj", "injected_refused", fbp,
                                     {"features": [], "sketches": []}, meta,
                                     fname,
                                     {"source": "injected", "fault": fname,
                                      "caught": True, "refused_before_build": True,
                                      "failing": [p["id"] for p in pre],
                                      "reverified": True, **fmeta}))
                    continue
                fgraph = _safe_resolve(fbp)
                if fgraph is not None:
                    jobs.append(_Job(tag + "_inj", "injected", fbp, fgraph,
                                     meta, fname,
                                     {"source": "injected", "fault": fname,
                                      "reverified": True, **fmeta}))

        if not jobs:
            break
        build_jobs = [j for j in jobs if j.kind != "injected_refused"]
        results = _run_batch(build_jobs, workers, scratch)
        stats["batches"] += 1
        stats["worker_slices"] += min(workers, len(build_jobs))

        # ---- finalize ---------------------------------------------------- #
        clean_ctx = {}   # base tag -> (bp, verdict, meta) for injected pairing
        for j in jobs:
            if j.kind == "injected_refused":
                continue
            res = results.get(j.tag)
            forced = j.kind == "stress"
            v = _verdict(j.bp, res, forced)
            graph_clean = {k: val for k, val in j.graph.items()
                           if k != "_analysis"}

            if j.kind == "clean":
                if not v["passed"]:
                    # EVERY non-passing clean draw is a natural failure — the
                    # highest-value repair signal — whether it failed to build
                    # or built-but-mismatched. Save all with a real diagnosis.
                    stats["build_failed"] += 1
                    failing = [a for a in v["assertions"] if not a["passed"]]
                    _save(_pack(j, v, graph_clean, "natural",
                                _natural_trace(v, failing)), "natural")
                    continue
                sampler.accept(j.meta["base_family"], j.meta["feature_seq"],
                               j.bp, j.meta)
                stats["passed"] += 1
                clean_ctx[j.tag] = v
                _save(_pack(j, v, graph_clean, "clean", None), "clean")

        # injected + stress finalize (need their clean context / just save)
        for j in jobs:
            if j.kind == "injected_refused":
                _save(_pack(j, {"passed": False, "refused": True,
                                "failed_preconditions": [],
                                "assertions": [], "measured": {},
                                "build_log": {}},
                            {"features": [], "sketches": []}, "injected",
                            j.trace), "injected")
                stats["injected"] += 1
                stats["faults_caught"] += 1
                continue
            if j.kind == "stress":
                res = results.get(j.tag)
                v = _verdict(j.bp, res, True)
                stats["stress"] += 1
                if not v["passed"]:
                    stats["faults_caught"] += 1
                _save(_pack(j, v, {k: val for k, val in j.graph.items()
                                   if k != "_analysis"}, "stress",
                            {**j.trace, "caught": not v["passed"],
                             "failing": [a["id"] for a in v["assertions"]
                                         if not a["passed"]]}), "stress")
            elif j.kind == "injected":
                base = j.tag[:-4]      # strip "_inj"
                if base not in clean_ctx:
                    continue            # clean didn't pass; drop the fault
                res = results.get(j.tag)
                v = _verdict(j.bp, res, False)
                caught = not v["passed"]
                stats["injected"] += 1
                if caught:
                    stats["faults_caught"] += 1
                _save(_pack(j, v, {k: val for k, val in j.graph.items()
                                   if k != "_analysis"}, "injected",
                            {**j.trace, "caught": caught,
                             "failing": [a["id"] for a in v["assertions"]
                                         if not a["passed"]]}), "injected")

    con.commit()
    stats["db_audit"] = corpus_db.audit(con)
    con.close()
    shutil.rmtree(scratch, ignore_errors=True)
    stats["elapsed_s"] = round(time.time() - t0, 1)
    stats["records_per_min"] = round(
        written / max(stats["elapsed_s"], 1e-9) * 60, 1)
    stats["sampler"] = sampler.metrics()
    return stats


def _natural_trace(verdict: dict, failing: list) -> dict:
    """Diagnosis for a natural clean-draw failure, from what actually failed."""
    if not verdict.get("build_ok"):
        err = (verdict.get("build_log", {}) or {}).get("error", "build failed")
        return {"source": "natural", "mechanism": "no_solid",
                "failing": [a.get("id") for a in failing],
                "diagnosis": f"natural build failure on a clean draw: {err}",
                "fix": "constrain the parameters so the geometry builds"}
    a = failing[0] if failing else {}
    m, t = a.get("measured"), a.get("target")
    detail = (f"measured {m:.4g} vs expected {t:.4g}"
              if isinstance(m, (int, float)) and isinstance(t, (int, float))
              else "did not hold on the built solid")
    return {"source": "natural", "mechanism": "verification_mismatch",
            "failing": [x.get("id") for x in failing],
            "diagnosis": f"natural verification failure: assertion "
                         f"'{a.get('id')}' ({a.get('kind')}) {detail} — the "
                         f"built solid does not match its prediction",
            "fix": f"correct the parameters so '{a.get('id')}' is satisfied"}


def _pack(job, verdict, graph, status, trace):
    payload = {
        "schema": "orion-forge-record-v1",
        "blueprint": job.bp.to_dict(),
        "feature_graph": graph,
        "analysis": job.graph.get("_analysis", {}),
        "verdict": {"tag": job.tag, **verdict},
        "recipe": job.meta.get("base_family"),
        "base_family": job.meta.get("base_family"),
        "attachments": job.meta.get("attachments", []),
        "datum_strategy": job.meta.get("datum_strategy", {}),
        "feature_seq": job.meta.get("feature_seq", []),
        "feature_sequence_hash": job.meta.get("feature_sequence_hash"),
    }
    if trace is not None:
        payload["repair_trace"] = trace
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch", type=int, default=240)
    ap.add_argument("--seed", type=int, default=100000)
    ap.add_argument("--out", default="data/forge/scale")
    args = ap.parse_args()
    stats = run(args.db, args.target, args.seed, args.workers, args.batch,
                args.out)
    printable = {k: v for k, v in stats.items()
                 if k not in ("sampler", "db_audit")}
    print(json.dumps(printable, indent=1))
    print("records/min:", stats["records_per_min"],
          "| signatures:", stats["sampler"]["distinct_signatures"])


if __name__ == "__main__":
    main()
