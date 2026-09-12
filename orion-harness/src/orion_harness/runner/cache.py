"""Content-addressed result cache (R4).

Key = sha256(canonical_json(task_spec) + submission.payload + verifier_version
+ env_digest). Never keyed on run_id alone -- that is the SWE-bench FAQ
footgun this harness explicitly avoids (§6.2): a cache keyed on run_id would
return a stale result even when the submission content changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..contracts import EnvDigest, Result, TaskSpec


def _canonical_json(obj) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def cache_key(
    task: TaskSpec,
    submission_payload: str,
    verifier_versions: dict[str, str],
    env: EnvDigest,
) -> str:
    parts = [
        _canonical_json(task),
        submission_payload,
        _canonical_json(dict(sorted(verifier_versions.items()))),
        _canonical_json(env),
    ]
    h = hashlib.sha256("\x00".join(parts).encode("utf-8"))
    return h.hexdigest()


class ResultCache:
    """Directory-backed content-addressed store. One JSON file per key."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> Result | None:
        p = self._path(key)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        result = Result.model_validate(data)
        return result.model_copy(update={"cached": True})

    def put(self, key: str, result: Result) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(result.model_dump(mode="json"), sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp.replace(p)  # atomic on POSIX and on Windows (same volume)

    def __contains__(self, key: str) -> bool:
        return self._path(key).exists()
