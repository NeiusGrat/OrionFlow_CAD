"""One run = one directory (§10): `run.json` (config/provenance) +
`results.jsonl` (one Result per line). `orion-harness rerun <run_dir>`
reproducing identical scores on deterministic tasks is a CI assertion this
package does not yet enforce end-to-end (no model adapter to replay
against in M1/M2) -- `run.json` records everything §10 asks for so that
check can be added later without a schema change.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..contracts import EnvDigest, Result


def _git_sha(repo_dir: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


class RunLog:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._results_path = self.run_dir / "results.jsonl"
        self._run_json_path = self.run_dir / "run.json"

    def write_run_config(
        self, env: EnvDigest, split: str, argv: list[str], model_id: str, extra: dict | None = None
    ) -> None:
        config = {
            "harness_version": __version__,
            "env": env.model_dump(mode="json"),
            "split": split,
            "model_id": model_id,
            "argv": argv,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "harness_git_sha": _git_sha(Path(__file__).resolve().parents[3]),
        }
        if extra:
            config.update(extra)
        self._run_json_path.write_text(
            json.dumps(config, sort_keys=True, indent=2), encoding="utf-8"
        )

    def read_run_config(self) -> dict | None:
        if not self._run_json_path.exists():
            return None
        return json.loads(self._run_json_path.read_text(encoding="utf-8"))

    def append(self, result: Result) -> None:
        with self._results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result.model_dump(mode="json"), sort_keys=True))
            f.write("\n")

    def read_all(self) -> list[Result]:
        if not self._results_path.exists():
            return []
        out = []
        with self._results_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(Result.model_validate(json.loads(line)))
        return out
