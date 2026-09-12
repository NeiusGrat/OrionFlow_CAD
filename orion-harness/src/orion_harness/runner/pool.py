"""Pre-warmed worker pool (F5).

Measured: `import build123d` costs ~2.47s; rebuilding a simple box
afterwards costs ~2ms. A cold subprocess per candidate is therefore
roughly 1000x overhead on the geometry step. Each worker here imports
build123d exactly once at startup and then serves up to `recycle_after`
jobs before the parent replaces it with a fresh one.

Timeout handling: a worker that doesn't respond within the task's
timeout_s is killed (SIGTERM, then SIGKILL after a grace period -- or
their Windows equivalents) and replaced; the job is reported as a timeout,
never silently retried against the same possibly-corrupted worker.
"""

from __future__ import annotations

import multiprocessing as mp
import time
import traceback
from dataclasses import dataclass

from .errors import TaskOutcome
from .isolate import apply_memory_limit, block_network
from .jobs import run_build_job

TERMINATE_GRACE_S = 5


def _worker_main(conn, memory_mb: int | None) -> None:
    from .._repo_root import ensure_repo_root_on_path

    ensure_repo_root_on_path()  # orionflow_ofl / app.* live one level up (R1)

    block_network()
    if memory_mb:
        apply_memory_limit(memory_mb)

    import build123d  # noqa: F401  -- pay the ~2.5s import cost exactly once per worker

    conn.send({"type": "ready"})

    while True:
        msg = conn.recv()
        if msg.get("type") == "shutdown":
            return
        job_id = msg["job_id"]
        try:
            result = run_build_job(msg["kind"], msg["payload"], msg["checks"])
            conn.send({"type": "ok", "job_id": job_id, "result": result})
        except TaskOutcome as e:
            conn.send(
                {
                    "type": "outcome",
                    "job_id": job_id,
                    "code": e.code,
                    "reason": e.reason,
                    "evidence": e.evidence or {},
                }
            )
        except BaseException as e:  # a geometry kernel abort surfaced as a
            # catchable Python exception in this sandbox (F6) -- the process
            # itself survives, so report exec_crash rather than relying on
            # the parent's EOF/timeout path.
            conn.send(
                {
                    "type": "outcome",
                    "job_id": job_id,
                    "code": "exec_crash",
                    "reason": f"{type(e).__name__}: {e}",
                    "evidence": {"traceback": traceback.format_exc()[-4000:]},
                }
            )


@dataclass
class _Worker:
    process: mp.Process
    conn: object  # multiprocessing.connection.Connection
    jobs_served: int = 0


class WorkerPool:
    def __init__(
        self,
        n_workers: int = 2,
        recycle_after: int = 50,
        memory_mb: int | None = None,
    ):
        self.n_workers = n_workers
        self.recycle_after = recycle_after
        self.memory_mb = memory_mb
        self._workers: list[_Worker] = [self._spawn() for _ in range(n_workers)]
        self._next_job_id = 0

    def _spawn(self) -> _Worker:
        parent_conn, child_conn = mp.Pipe()
        proc = mp.Process(
            target=_worker_main, args=(child_conn, self.memory_mb), daemon=True
        )
        proc.start()
        ready = parent_conn.recv()  # blocks until `import build123d` finishes
        if ready.get("type") != "ready":
            raise RuntimeError(f"worker failed to start: {ready}")
        return _Worker(process=proc, conn=parent_conn)

    def _kill(self, proc: mp.Process) -> None:
        if not proc.is_alive():
            return
        proc.terminate()
        proc.join(timeout=TERMINATE_GRACE_S)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=TERMINATE_GRACE_S)

    def _replace(self, index: int) -> None:
        self._kill(self._workers[index].process)
        self._workers[index] = self._spawn()

    def submit(self, kind: str, payload, checks: list[dict], timeout_s: float) -> dict:
        """Run one job to completion on the least-loaded worker.

        `checks` is the task's CheckSpec list, serialized to plain dicts
        (`[c.model_dump() for c in task.checks]`) -- the worker dispatches
        each check through the registry generically (runner/jobs.py); this
        pool has no opinion about what a task does or does not check.

        Returns {"status": "ok", "wall_s", "result"} or
                {"status": "outcome", "wall_s", "code", "reason", "evidence"} or
                {"status": "timeout", "wall_s"} or
                {"status": "crash", "wall_s", "reason"}.
        """

        index = min(range(len(self._workers)), key=lambda i: self._workers[i].jobs_served)
        worker = self._workers[index]
        self._next_job_id += 1
        job_id = self._next_job_id
        worker.conn.send({"job_id": job_id, "kind": kind, "payload": payload, "checks": checks})

        start = time.monotonic()
        if not worker.conn.poll(timeout=timeout_s):
            self._replace(index)
            return {"status": "timeout", "wall_s": time.monotonic() - start}

        try:
            msg = worker.conn.recv()
        except EOFError:
            self._replace(index)
            return {
                "status": "crash",
                "wall_s": time.monotonic() - start,
                "reason": "worker process died without a response (possible kernel abort -- see F6 caveat in OF-TR-002 §3)",
            }

        worker.jobs_served += 1
        recycle = worker.jobs_served >= self.recycle_after
        wall_s = time.monotonic() - start

        if msg["type"] == "ok":
            if recycle:
                self._replace(index)
            return {"status": "ok", "wall_s": wall_s, "result": msg["result"]}

        # msg["type"] == "outcome": the worker itself is fine, the submission failed.
        if recycle:
            self._replace(index)
        return {
            "status": "outcome",
            "wall_s": wall_s,
            "code": msg["code"],
            "reason": msg["reason"],
            "evidence": msg.get("evidence", {}),
        }

    def shutdown(self) -> None:
        for w in self._workers:
            try:
                w.conn.send({"type": "shutdown"})
            except Exception:
                pass
            w.process.join(timeout=TERMINATE_GRACE_S)
            if w.process.is_alive():
                w.process.terminate()

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown()
