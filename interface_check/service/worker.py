"""One job, one isolated child process, one watchdog.

    start -> claim (QUEUED->RUNNING, compare-and-set) -> private scratch dir
          -> download inputs -> complexity gate (route to a bigger tier, or refuse)
          -> analysis in a spawned child process  <- watchdog: memory, time, cancel, heartbeat
          -> output size check -> upload outputs -> results to the store -> SUCCEEDED
          -> always: scratch dir removed, worker_runs row written, queue pumped

The geometry kernel runs in a child process on purpose. OpenCASCADE holds
memory the Python allocator never returns; when the child exits the OS takes
all of it back. The parent stays small, so it can always see the child's
memory, kill it at the cap and report MEMORY_LIMIT instead of being killed by
the container's OOM killer with nothing recorded.

Idempotent: a job in a terminal state is never touched, results are replaced
in one transaction, and outputs land under the job's own prefix.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import shutil
import socket
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from ..errors import AnalysisError
from ..inspect_step import tier_resources
from ..limits import TIER_USD_PER_S, limits_for
from ..pipeline import gate
from .db import TERMINAL
from .jobs import after_failure, allowed, pump, tier_rank
from .storage import open_storage

POLL_S = 0.25
CANCEL_POLL_S = 2.0
HEARTBEAT_S = 5.0
#: share of the tier's memory the analysis may use; the rest is the parent, the OS and headroom
MEMORY_SHARE = 0.85
OUTPUTS = ("report.json", "report.pdf", "model.glb")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------ child

def _child(spec: dict) -> None:
    """Runs in the spawned process: the only place geometry is computed."""
    out = Path(spec["output"])
    progress = Path(spec["progress"])

    def report_progress(stage: str, info: dict) -> None:
        tmp = progress.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stage": stage, **info, "t": time.time()}))
        os.replace(tmp, progress)

    result: dict = {"ok": False}
    try:
        from ..cache import FeatureCache
        from ..limits import limits_for as _limits
        from ..pipeline import run_check
        from ..report import write_json, write_pdf

        storage = open_storage(spec["storage"])
        cache = FeatureCache(storage=storage) if spec.get("cache", True) else None
        inp = spec["inputs"]
        report = run_check(
            inp["step"], bom=inp.get("bom"), prev_step=inp.get("prev_step"), prev_bom=inp.get("prev_bom"),
            urdf=inp.get("urdf"), urdf_map=inp.get("urdf_map"), drawings=inp.get("drawing", []),
            datasheets=inp.get("datasheet", []), vendor_steps=inp.get("vendor_step", []),
            glb=out / "model.glb", cache=cache, limits=_limits(spec["plan"]), progress=report_progress,
            workdir=spec["working"])
        write_json(report, out / "report.json")
        write_pdf(report, out / "report.pdf")
        result = {"ok": True, "summary": {s: report.count(s) for s in ("high", "medium", "low", "info")},
                  "cache": report.stats.get("cache", {}), "stage": "final_report"}
    except AnalysisError as e:
        result = {"ok": False, "code": e.code, "message": str(e), "stage": e.stage}
    except MemoryError:
        result = {"ok": False, "code": "MEMORY_LIMIT", "message": "the analysis ran out of memory"}
    except Exception as e:  # noqa: BLE001 - every failure becomes a structured result
        kernel = type(e).__module__.startswith("OCP") or "Standard_" in type(e).__name__
        result = {"ok": False, "code": "FREECAD_FAILURE" if kernel else "WORKER_FAILURE",
                  "message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=6)}
    tmp = out / "result.json.tmp"
    tmp.write_text(json.dumps(result))
    os.replace(tmp, out / "result.json")


def _tree_rss(pid: int) -> int:
    import psutil
    try:
        p = psutil.Process(pid)
        return p.memory_info().rss + sum(c.memory_info().rss for c in p.children(recursive=True))
    except psutil.Error:
        return 0


def _kill_tree(proc) -> None:
    import psutil
    try:
        p = psutil.Process(proc.pid)
        for c in p.children(recursive=True):
            c.kill()
        p.kill()
    except psutil.Error:
        pass
    proc.join(10)


def run_isolated(spec: dict, memory_mb: int, runtime_s: float, cancelled=lambda: False,
                 heartbeat=lambda stage: None) -> dict:
    """Run :func:`_child` under the watchdog. Always returns a structured result."""
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_child, args=(spec,), daemon=True)
    t0 = time.time()
    proc.start()
    peak, last_cancel, last_beat = 0, 0.0, 0.0
    progress = Path(spec["progress"])
    stage = "starting"
    verdict = None
    while proc.is_alive():
        rss = _tree_rss(proc.pid)
        peak = max(peak, rss)
        now = time.time()
        if rss > memory_mb * 2**20:
            verdict = {"ok": False, "code": "MEMORY_LIMIT",
                       "message": f"stopped at {rss / 2**20:.0f} MB, over the {memory_mb} MB limit"}
        elif now - t0 > runtime_s:
            verdict = {"ok": False, "code": "TIMEOUT", "message": f"stopped after {runtime_s:.0f} s"}
        elif now - last_cancel > CANCEL_POLL_S:
            last_cancel = now
            if cancelled():
                verdict = {"ok": False, "code": "CANCELLED", "message": "cancelled by the user"}
        if verdict:
            _kill_tree(proc)
            break
        if now - last_beat > HEARTBEAT_S:
            last_beat = now
            try:
                stage = json.loads(progress.read_text()).get("stage", stage)
            except (OSError, ValueError):
                pass
            heartbeat(stage)
        time.sleep(POLL_S)
    proc.join(5)
    try:
        stage = json.loads(progress.read_text()).get("stage", stage)
    except (OSError, ValueError):
        pass
    if verdict is None:
        res_path = Path(spec["output"]) / "result.json"
        if res_path.exists():
            verdict = json.loads(res_path.read_text())
        else:
            verdict = {"ok": False, "code": "WORKER_FAILURE",
                       "message": f"analysis process exited with code {proc.exitcode} and no result"}
    verdict.setdefault("stage", stage)
    verdict["peak_mb"] = round(peak / 2**20, 1)
    verdict["runtime_s"] = round(time.time() - t0, 3)
    return verdict


# ------------------------------------------------------------------ job

def execute_job(job_id: str, ctx, worker_tier: str | None = None) -> str:
    """Run one attempt of one job. Returns the job's state afterwards."""
    store = ctx.store
    job = store.get_job(job_id)
    if job is None:
        return "MISSING"
    if job["state"] in TERMINAL:
        return job["state"]
    tier = worker_tier or job["tier"]
    attempt = job["attempts"] + 1
    if not store.transition(job_id, ["QUEUED"], state="RUNNING", tier=tier, attempts=attempt, started_at=_now(),
                            heartbeat_at=_now(), stage="downloading", failure_code=None, error=None):
        return (store.get_job(job_id) or {}).get("state", "MISSING")
    job = store.get_job(job_id)
    limits = limits_for(job["plan"])
    mem_gb, cpus = tier_resources(tier)
    memory_mb = int(min(limits.max_memory_mb, mem_gb * 1024 * MEMORY_SHARE))
    run = {"job_id": job_id, "user_id": job["user_id"], "attempt": attempt, "tier": tier,
           "worker_id": f"{socket.gethostname()}:{os.getpid()}", "started_at": _now(),
           "memory_limit_mb": memory_mb, "cpu_count": os.cpu_count()}
    work = Path(tempfile.mkdtemp(prefix=f"ic-{job_id[:8]}-", dir=ctx.cfg.work_root or None))
    state = "RUNNING"
    try:
        state = _attempt(job, tier, attempt, work, memory_mb, limits, run, ctx)
        return state
    finally:
        shutil.rmtree(work, ignore_errors=True)
        run["finished_at"] = _now()
        run.setdefault("runtime_s", (run["finished_at"] - run["started_at"]).total_seconds())
        run["cost_usd"] = round(run["runtime_s"] * TIER_USD_PER_S.get(tier, 0.0), 6)
        run.setdefault("outcome", state)
        try:
            store.add_worker_run(**run)
        except Exception:  # noqa: BLE001 - observability must never fail the job
            pass
        try:
            pump(store, ctx.dispatcher, ctx.cfg.global_concurrency)
        except Exception:  # noqa: BLE001
            pass


def _attempt(job, tier, attempt, work, memory_mb, limits, run, ctx) -> str:
    store, storage = ctx.store, ctx.storage
    job_id = job["id"]
    inp, working, out = work / "input", work / "working", work / "output"
    for d in (inp, working, out):
        d.mkdir(parents=True)

    def fail(code: str, message: str, stage: str = "") -> str:
        run.update(failure_code=code, stage=stage)
        if code == "CANCELLED":
            store.transition(job_id, ["RUNNING"], state="CANCELLED", finished_at=_now(), error=message)
            run["outcome"] = "CANCELLED"
            return "CANCELLED"
        tier_attempts = store.run_count(job_id, tier) + 1
        d = after_failure(store.get_job(job_id), code, tier_attempts)
        if d.action == "retry":
            store.transition(job_id, ["RUNNING"], state="QUEUED", tier=d.tier, dispatched_at=None,
                             failure_code=code, error=message, stage=f"retry on {d.tier} after {code}")
            run["outcome"] = "RETRY"
            return "QUEUED"
        store.transition(job_id, ["RUNNING"], state=d.state, failure_code=code, error=message, stage=stage,
                         finished_at=_now())
        run["outcome"] = d.state
        return d.state

    # inputs
    files: dict = {}
    try:
        for doc in store.documents(job_id):
            dst = inp / doc["kind"] / doc["filename"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            storage.get_file(doc["storage_key"], dst)
            if doc["kind"] in ("drawing", "datasheet", "vendor_step"):
                files.setdefault(doc["kind"], []).append(str(dst))
            else:
                files[doc["kind"]] = str(dst)
    except Exception as e:  # noqa: BLE001
        return fail("STORAGE_FAILURE", f"could not download inputs: {e}", "downloading")
    step = Path(files["step"])
    run.update(file_size=step.stat().st_size, file_hash=_sha256(step))

    # complexity gate: refuse, or route to the tier that can hold it
    store.update(job_id, stage="complexity", heartbeat_at=_now())
    try:
        c = gate(step, limits)
    except AnalysisError as e:
        return fail(e.code, str(e), "file_validation")
    run.update(face_count=c.face_count, part_count=c.part_count)
    store.update(job_id, complexity={k: v for k, v in c.to_dict().items() if k != "counts"} | {"counts": c.counts})
    if c.tier == "REJECT" or not allowed(c.tier, job["plan"]):
        need = "more than the largest worker" if c.tier == "REJECT" else f"a {c.tier} worker"
        return fail("MEMORY_LIMIT" if c.tier == "REJECT" else "TOO_MANY_FACES",
                    f"estimated {c.estimated_memory_gb} GB needs {need}; the {limits.plan} plan allows "
                    f"up to {limits.max_tier}", "complexity")
    if tier_rank(c.tier) > tier_rank(tier):
        store.transition(job_id, ["RUNNING"], state="QUEUED", tier=c.tier, dispatched_at=None,
                         attempts=attempt - 1, stage=f"routed to {c.tier} (estimated {c.estimated_memory_gb} GB)")
        run.update(outcome="ROUTED", stage="complexity")
        return "QUEUED"

    # analysis, isolated
    spec = {"inputs": files, "output": str(out), "working": str(working), "progress": str(working / "progress.json"),
            "storage": ctx.cfg.storage_spec(), "plan": job["plan"], "cache": True}

    def cancelled() -> bool:
        j = store.get_job(job_id)
        return bool(j and (j["cancel_requested"] or j["state"] != "RUNNING"))

    def heartbeat(stage: str) -> None:
        store.update(job_id, heartbeat_at=_now(), stage=stage)

    res = run_isolated(spec, memory_mb, limits.max_runtime_s, cancelled, heartbeat)
    run.update(peak_memory_mb=res["peak_mb"], runtime_s=res["runtime_s"], stage=res.get("stage"),
               cache_hits=res.get("cache", {}).get("hits"), cache_misses=res.get("cache", {}).get("misses"))
    if not res["ok"]:
        return fail(res["code"], res.get("message", ""), res.get("stage", ""))

    # outputs: size limit, then upload, then results
    sizes = {n: (out / n).stat().st_size for n in OUTPUTS if (out / n).exists()}
    if sum(sizes.values()) > limits.max_output_mb * 2**20 and "model.glb" in sizes:
        (out / "model.glb").unlink()                  # the 3D view is the first thing to give up
        sizes.pop("model.glb")
    if sum(sizes.values()) > limits.max_output_mb * 2**20:
        return fail("OUTPUT_TOO_LARGE", f"{sum(sizes.values()) / 2**20:.0f} MB of results", "final_report")
    keys = {}
    try:
        for n in sizes:
            keys[n] = f"jobs/{job_id}/output/{n}"
            storage.put_file(keys[n], out / n)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        store.save_results(job_id, report, keys, (store.get_job(job_id) or {}).get("complexity"))
    except Exception as e:  # noqa: BLE001
        return fail("STORAGE_FAILURE", f"could not store results: {e}", "final_report")
    ok = store.transition(job_id, ["RUNNING"], state="SUCCEEDED", finished_at=_now(), stage="done",
                          summary=res["summary"] | {"cache": res.get("cache", {})}, failure_code=None, error=None)
    run["outcome"] = "SUCCEEDED" if ok else "LATE"     # LATE: cancelled while finishing; results kept
    return "SUCCEEDED" if ok else (store.get_job(job_id) or {}).get("state", "MISSING")


def probe() -> dict:
    """What a worker container actually has: CPUs, memory, a working kernel."""
    import psutil
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GProp import GProp_GProps

    from ..version import ENGINE_VERSION
    t0 = time.time()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape(), props)
    return {"ok": abs(props.Mass() - 6000.0) < 1e-6, "cpu_count": os.cpu_count(),
            "host_memory_mb": round(psutil.virtual_memory().total / 2**20),
            "container_memory_limit_mb": _cgroup_memory_mb(), "container_cpu_limit": _cgroup_cpus(),
            "kernel_ms": round((time.time() - t0) * 1000, 1), "engine_version": ENGINE_VERSION,
            "host": socket.gethostname()}


def _cgroup_memory_mb() -> int | None:
    """The container's real memory limit (psutil reports the host's)."""
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = Path(p).read_text().strip()
            return None if v == "max" else round(int(v) / 2**20)
        except (OSError, ValueError):
            continue
    return None


def _cgroup_cpus() -> float | None:
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        return None if quota == "max" else round(int(quota) / int(period), 2)
    except (OSError, ValueError):
        return None
