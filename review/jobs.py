"""Run a review job: fetch the revision's files, build the Model Graph, store it.

The API never does geometry itself. OpenCASCADE holds the GIL for seconds at a
time, so a model read in the API process would freeze every other request.
Jobs therefore run in worker processes (``REVIEW_WORKERS``, default 2); each
writes its own step progress to the database, which the API reads back.

Every step records state (pending | running | done | skipped | failed),
seconds and a note, so a slow or failed run says exactly where.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .store import Store, now

_POOL: ProcessPoolExecutor | None = None


def storage_spec() -> dict:
    return {
        "kind": os.environ.get("REVIEW_STORAGE", "local"),
        "root": os.environ.get("REVIEW_STORAGE_ROOT", "data/review/store"),
        "bucket": os.environ.get("REVIEW_S3_BUCKET", ""),
        "endpoint": os.environ.get("REVIEW_S3_ENDPOINT", ""),
        "region": os.environ.get("REVIEW_S3_REGION", "us-east-1"),
        "key": os.environ.get("REVIEW_S3_KEY", ""),
        "secret": os.environ.get("REVIEW_S3_SECRET", ""),
    }


def open_storage(spec: dict | None = None):
    from interface_check.service.storage import open_storage as _open
    return _open(spec or storage_spec())


def submit(job_id: str, db_url: str) -> None:
    """Queue a job on the worker pool (or run inline when REVIEW_INLINE=1, for tests)."""
    global _POOL
    if os.environ.get("REVIEW_INLINE") == "1":
        run_job(job_id, db_url, storage_spec())
        return
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=int(os.environ.get("REVIEW_WORKERS", "2")))
    _POOL.submit(run_job, job_id, db_url, storage_spec())


class _Steps:
    def __init__(self, store: Store, job_id: str, steps: list[dict]):
        self.store, self.job_id, self.steps = store, job_id, steps
        self.t0: dict[str, float] = {}

    def _save(self) -> None:
        self.store.update_job(self.job_id, steps=json.loads(json.dumps(self.steps)))

    def _get(self, key: str) -> dict:
        return next(s for s in self.steps if s["key"] == key)

    def start(self, key: str, note: str = "") -> None:
        s = self._get(key)
        s.update(state="running", note=note, started_at=now().isoformat())
        self.t0[key] = time.perf_counter()
        self._save()

    def finish(self, key: str, note: str | None = None, state: str = "done") -> None:
        s = self._get(key)
        if key in self.t0:
            s["seconds"] = round(time.perf_counter() - self.t0[key], 2)
        s.update(state=state, ended_at=now().isoformat())
        if note is not None:
            s["note"] = note
        self._save()

    def fail_running(self, note: str) -> None:
        for s in self.steps:
            if s["state"] == "running":
                s["note"] = note
                self.finish(s["key"], state="failed")


def _pick_step(files: list[dict], primary: str | None) -> dict | None:
    steps = [f for f in files if f["kind"] == "step"]
    if primary:
        chosen = next((f for f in steps if f["id"] == primary), None)
        if chosen:
            return chosen
    return max(steps, key=lambda f: f["size"], default=None)


def attach_bom(graph, boms: list[dict], storage, store: Store, rid: str, job_id: str | None, work: Path) -> str:
    """Parse every BOM file of the revision, match rows to parts and write the result into the graph."""
    from .bom import apply, match_with_llm, parse, reconcile
    from .llm import Gateway

    rows, infos, problems = [], [], []
    for f in boms:
        local = work / f"bom_{f['id']}_{Path(f['name']).name}"
        storage.get_file(f["storage_key"], local)
        try:
            r, info = parse(f["name"], local.read_bytes())
            rows += r
            infos.append(info)
        except ValueError as e:
            problems.append(str(e))
    gw = Gateway(store, job_id)
    records = reconcile(rows, graph, llm_match=match_with_llm(gw), human=store.bom_links_for(rid))
    apply(graph, records)
    graph.documents = [d for d in graph.documents if d.get("kind") != "bom"] + [{"kind": "bom", **i} for i in infos]
    by = {}
    for r in records:
        by[r["method"]] = by.get(r["method"], 0) + 1
    note = f"{len(records)} rows · " + " · ".join(f"{v} {k}" for k, v in sorted(by.items()))
    if not gw.available:
        note += " · AI matching off"
    if problems:
        note += " · " + "; ".join(problems)
    return note


def attach_sim(graph, sims: list[dict], files: list[dict], storage, store: Store, rid: str, work: Path) -> str:
    """Parse the sim model, map its bodies to CAD instances and compare mass properties; store it in the graph."""
    from .sim import analyse, cad_axes, map_bodies, parse_sim, pick_robot, read_aux

    f = sims[0]
    local = work / f"sim_{f['id']}_{Path(f['name']).name}"
    storage.get_file(f["storage_key"], local)
    model = pick_robot(parse_sim(f["name"], local.read_bytes()))
    aux = []
    for x in files:
        if x["name"].lower().endswith(".json") and x["size"] < 5_000_000:
            p = work / f"aux_{x['id']}.json"
            storage.get_file(x["storage_key"], p)
            aux.append((x["name"], p.read_bytes()))
    reg, man = read_aux(aux)
    doc = {"kind": "sim", "file": f["name"], "format": model["format"], "model": model.get("model"), "root": model["root"],
           "copies": model.get("copies", 1), "robot": {"bodies": model["bodies"], "joints": model["joints"]},
           "registration": reg, "manifest": {"file": man["file"], "source_sha256": man.get("source_sha256"),
                                              "meshes": man["meshes"]} if man else None}
    graph.documents = [d for d in graph.documents if d.get("kind") != "sim"] + [doc]
    return refresh_sim(graph, store.sim_links_for(rid))


def refresh_sim(graph, human: dict | None = None) -> str:
    """(Re)compute the sim mapping and comparison from the stored sim document — no file access, no geometry."""
    from .sim import analyse, cad_axes, map_bodies

    doc = next((d for d in graph.documents if d.get("kind") == "sim"), None)
    if doc is None:
        return "no sim model"
    robot = {"root": doc["root"], **doc["robot"]}
    reg = doc.get("registration")
    man = doc.get("manifest")
    mapping = map_bodies(robot, graph, man, human=human, reg=reg)
    result = analyse(graph, robot, mapping, reg)
    parent_ids = {b["body"]: b["instances"] for b in result["bodies"]}
    for j in result["joints"]:
        j["cad_axes"] = cad_axes(graph, reg, parent_ids.get(j["parent"], []), parent_ids.get(j["body"], []))[:3]
    doc["analysis"] = result
    graph.joints = [{"source": doc["format"], **j} for j in result["joints"]]
    mapped = sum(len(b["instances"]) for b in result["bodies"])
    return (f"{len(result['bodies'])} bodies · {len(result['joints'])} joints · {mapped}/{len(graph.instances)} CAD instances mapped"
            + ("" if reg else " · no registration: frame-free checks only"))


def run_job(job_id: str, db_url: str, spec: dict) -> None:
    """Worker entry point. Never raises: every failure is written to the job."""
    store = Store(db_url)
    job = store.job(job_id)
    if job is None or not store.update_job(job_id, only_if=("queued",), state="running", started_at=now()):
        return
    rid = job["revision_id"]
    store.set_revision_status(rid, "running")
    steps = _Steps(store, job_id, job["steps"])
    work = Path(tempfile.mkdtemp(prefix="review_"))
    try:
        from .ingest import build_graph
        from .schema import SourceFile

        storage = open_storage(spec)
        rev = store.revision(rid)
        files = store.files_for(rid)
        step_file = _pick_step(files, rev.get("primary_file_id"))
        if step_file is None:
            raise RuntimeError("this revision has no STEP file: add a STEP assembly or part to run a review")
        local = work / Path(step_file["name"]).name
        storage.get_file(step_file["storage_key"], local)

        sources = [SourceFile(name=f["name"], kind=f["kind"], sha256=f["sha256"], size=f["size"]) for f in files]
        glb = work / "viewer.glb"

        def progress(key: str, note: str) -> None:
            for st in steps.steps:                 # each stage closes the one before it
                if st["state"] == "running":
                    steps.finish(st["key"])
            steps.start(key, note)

        # build_graph reports "parse" first; progress() opens each step as it starts
        graph = build_graph(local, rid, files=[s for s in sources if s.name == step_file["name"]] +
                            [s for s in sources if s.name != step_file["name"]], glb_path=glb, progress=progress)
        steps.finish("mesh", f"{graph.stats.triangles:,} triangles")

        boms = [f for f in files if f["kind"] == "bom"]
        steps.start("bom", "reading BOM" if boms else "")
        overrides = store.overrides_for(rev["project_id"])
        if boms:
            note = attach_bom(graph, boms, storage, store, rid, job_id, work)
        else:
            note = "no BOM in this revision"
        from .bom import apply_overrides
        n_over = apply_overrides(graph, overrides)
        if n_over:
            note += f" · {n_over} part override{'s' if n_over > 1 else ''}"
        steps.finish("bom", note, state="done" if boms or n_over else "skipped")

        sims = [f for f in files if f["kind"] in ("mjcf", "urdf")]
        steps.start("sim", "reading the sim model" if sims else "")
        if sims:
            steps.finish("sim", attach_sim(graph, sims, files, storage, store, rid, work))
        else:
            steps.finish("sim", "no URDF or MJCF in this revision", state="skipped")
        for key, note in (("features", f"{graph.stats.features} features"), ("contacts", f"{graph.stats.contacts} contacts")):
            st = next(x for x in steps.steps if x["key"] == key)
            st["note"] = note
        steps._save()

        steps.start("graph", "saving")
        glb_key = f"review/{rid}/viewer.glb"
        storage.put_file(glb_key, glb)
        store.save_graph(rid, graph.schema_version, json.loads(graph.model_dump_json()), glb_key)
        steps.finish("graph", f"{graph.stats.parts} parts · {graph.stats.instances} instances")

        steps.start("checks", "running the check catalogue")
        from .checks import run_checks
        results, runs = run_checks(graph)
        counts = store.save_check_results(rid, job_id, results, runs)
        ran = sum(1 for r in runs if r["status"] in ("passed", "findings"))
        not_run = sum(1 for r in runs if r["status"] == "not_run")
        errors = sum(1 for r in runs if r["status"] == "error")
        note = f"{ran} run · {not_run} not run · {len(results)} findings ({counts['new']} new)"
        steps.finish("checks", note + (f" · {errors} check errors" if errors else ""))

        if store.update_job(job_id, only_if=("running",), state="done", ended_at=now()):
            store.set_revision_status(rid, "done")
    except Exception as e:  # noqa: BLE001 - reported on the job, never lost
        msg = f"{type(e).__name__}: {e}"
        steps.fail_running(msg)
        store.update_job(job_id, only_if=("running",), state="failed", error=msg + "\n" + traceback.format_exc()[-2000:],
                         ended_at=now())
        store.set_revision_status(rid, "failed")
    finally:
        shutil.rmtree(work, ignore_errors=True)
