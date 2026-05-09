"""Phase 5b: Validate transpiled build123d code by executing it.

For each row in b123d/<split>.jsonl with transpile_ok=True:
  - exec the b123d code in an isolated namespace
  - check that `result` is bound to a build123d Part / Compound
  - record success/failure and elapsed time

Writes b123d_validated/<split>.jsonl with added 'b123d_ok' / 'b123d_error' fields.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B123D_DIR = ROOT / "b123d"
OUT_DIR = ROOT / "b123d_validated"


def validate(code: str, timeout_s: float = 8.0) -> tuple[bool, str, float]:
    """Try to exec code in a fresh namespace; return (ok, error, elapsed_s)."""
    t0 = time.time()
    ns: dict = {}
    try:
        compiled = compile(code, "<b123d>", "exec")
        exec(compiled, ns)
    except BaseException as e:  # OCP can raise non-Exception classes
        return False, f"{type(e).__name__}: {str(e)[:200]}", time.time() - t0
    if "result" not in ns:
        return False, "no_result_var", time.time() - t0
    res = ns["result"]
    has_vol = hasattr(res, "volume")
    if not has_vol:
        return False, f"result_type={type(res).__name__}", time.time() - t0
    try:
        v = res.volume
        if v <= 0:
            return False, "zero_volume", time.time() - t0
    except BaseException as e:
        return False, f"volume_check: {type(e).__name__}: {str(e)[:200]}", time.time() - t0
    return True, "", time.time() - t0


def _load_done_uuids(path: Path) -> set[str]:
    """Return uuids already validated in `path`. Used for resumability."""
    s: set[str] = set()
    if not path.exists():
        return s
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                if "b123d_ok" in row:
                    s.add(row["uuid"])
            except Exception:
                continue
    return s


def _crash_sentinel_path(out_path: Path) -> Path:
    return out_path.with_suffix(".inprogress")


def _read_crash_sentinel(out_path: Path) -> str | None:
    p = _crash_sentinel_path(out_path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or None
    return None


def _write_crash_sentinel(out_path: Path, uuid: str) -> None:
    _crash_sentinel_path(out_path).write_text(uuid, encoding="utf-8")


def _clear_crash_sentinel(out_path: Path) -> None:
    p = _crash_sentinel_path(out_path)
    if p.exists():
        p.unlink()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = sys.argv[1:] or ["train", "validation", "test"]
    summary: dict = {}
    for split in splits:
        in_path = B123D_DIR / f"{split}.jsonl"
        if not in_path.exists():
            print(f"[{split}] missing {in_path}, skip")
            continue
        out_path = OUT_DIR / f"{split}.jsonl"
        done = _load_done_uuids(out_path)
        if done:
            print(f"[{split}] resuming: {len(done)} uuids already validated")
        # Honour a crash sentinel: the uuid we were processing when we died.
        crashed_uuid = _read_crash_sentinel(out_path)
        if crashed_uuid:
            print(f"[{split}] crash-skip uuid {crashed_uuid[:8]} (hard-crashed previous run)")
        n_in = n_attempted = n_ok = 0
        err_hist: dict[str, int] = {}
        t0 = time.time()
        with in_path.open(encoding="utf-8") as fin, out_path.open("a", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                n_in += 1
                if row["uuid"] in done:
                    if row.get("transpile_ok"):
                        n_attempted += 1
                    continue
                if row["uuid"] == crashed_uuid:
                    # Mark as a hard-crash failure and move on permanently.
                    row["b123d_ok"] = False
                    row["b123d_error"] = "hard_crash_previous_run"
                    fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fout.flush()
                    _clear_crash_sentinel(out_path)
                    crashed_uuid = None
                    continue
                if not row.get("transpile_ok"):
                    row["b123d_ok"] = False
                    row["b123d_error"] = ""
                    fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fout.flush()
                    continue
                n_attempted += 1
                _write_crash_sentinel(out_path, row["uuid"])
                ok, err, dt = validate(row["b123d_code"])
                _clear_crash_sentinel(out_path)
                row["b123d_ok"] = ok
                row["b123d_error"] = err
                row["b123d_validate_s"] = round(dt, 3)
                if ok:
                    n_ok += 1
                else:
                    bucket = err.split(":", 1)[0]
                    err_hist[bucket] = err_hist.get(bucket, 0) + 1
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                fout.flush()
                if n_attempted % 200 == 0:
                    print(f"  [{split}] attempted={n_attempted} ok={n_ok} elapsed={time.time()-t0:.0f}s", flush=True)
        summary[split] = {
            "in": n_in,
            "attempted": n_attempted,
            "ok": n_ok,
            "elapsed_s": round(time.time() - t0, 1),
            "top_errors": dict(sorted(err_hist.items(), key=lambda kv: -kv[1])[:8]),
        }
        print(f"[{split}] {n_ok}/{n_attempted} validated ({100*n_ok/max(1,n_attempted):.1f}%) -> {out_path}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
