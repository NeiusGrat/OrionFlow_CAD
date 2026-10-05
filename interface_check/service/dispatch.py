"""Where a job runs.

LocalDispatcher  a small thread pool; each thread only supervises — the
                 analysis itself runs in an isolated child process. For
                 development and single-machine installs.
ModalDispatcher  one Modal function per worker tier (cad_small, cad_medium,
                 cad_large, cad_extreme), each container taking exactly one job.
                 The API only calls ``.spawn``; it never waits on geometry.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Config
from .db import Store
from .storage import Storage, open_storage


class LocalDispatcher:
    def __init__(self, ctx_getter, max_workers: int):
        self._ctx = ctx_getter
        self.pool = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="ic-worker")
        self._n = 0
        self._lock = threading.Lock()

    def submit(self, job_id: str, tier: str) -> str:
        from .worker import execute_job
        with self._lock:
            self._n += 1
            ref = f"local:{self._n}"
        self.pool.submit(execute_job, job_id, self._ctx(), tier)
        return ref

    def cancel(self, ref: str) -> None:
        """Nothing to do: the worker's watchdog polls the cancel flag and kills its child."""

    def health(self, probe_workers: bool = False) -> dict:
        out = {"kind": "local", "ok": not self.pool._shutdown, "tiers": {}}
        if probe_workers:
            from .worker import probe
            out["tiers"]["LOCAL"] = probe()
        return out


class ModalDispatcher:
    def __init__(self, app_name: str):
        self.app_name = app_name

    def submit(self, job_id: str, tier: str) -> str:
        import modal
        fn = modal.Function.from_name(self.app_name, f"cad_{tier.lower()}")
        return fn.spawn(job_id, tier).object_id

    def cancel(self, ref: str) -> None:
        import modal
        if ref and not ref.startswith("local:"):
            modal.FunctionCall.from_id(ref).cancel()

    def health(self, probe_workers: bool = False) -> dict:
        """Every tier function is deployed; with ``probe_workers`` each one also runs a kernel probe."""
        import json
        from concurrent.futures import ThreadPoolExecutor

        import modal
        from ..inspect_step import TIERS

        def one(tier: str) -> dict:
            t0 = time.time()
            try:
                fn = modal.Function.from_name(self.app_name, f"cad_{tier.lower()}")
                fn.hydrate()
                if not probe_workers:
                    return {"deployed": True}
                res = json.loads(fn.remote("__probe__", tier))
                return {"deployed": True, **res, "roundtrip_s": round(time.time() - t0, 2)}
            except Exception as e:  # noqa: BLE001 - a broken tier is reported, not raised
                return {"deployed": False, "ok": False, "error": f"{type(e).__name__}: {e}"}

        names = [t[0] for t in TIERS]
        with ThreadPoolExecutor(len(names)) as ex:
            tiers = dict(zip(names, ex.map(one, names)))
        ok = all(t.get("deployed") and t.get("ok", True) for t in tiers.values())
        return {"kind": "modal", "app": self.app_name, "ok": ok, "tiers": tiers}


@dataclass
class Context:
    cfg: Config
    store: Store
    storage: Storage
    dispatcher: object


_ctx: Context | None = None
_lock = threading.Lock()


def context(cfg: Config | None = None, reset: bool = False) -> Context:
    """Process-wide context built from the environment (or ``cfg``)."""
    global _ctx
    with _lock:
        if _ctx is None or reset or cfg is not None:
            cfg = cfg or Config()
            store = Store(cfg.database_url)
            storage = open_storage(cfg.storage_spec())
            dispatcher = (ModalDispatcher(cfg.modal_app) if cfg.dispatch == "modal"
                          else LocalDispatcher(lambda: _ctx, cfg.global_concurrency))
            _ctx = Context(cfg, store, storage, dispatcher)
        return _ctx
