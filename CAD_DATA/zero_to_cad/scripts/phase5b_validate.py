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
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", time.time() - t0
    if "result" not in ns:
        return False, "no_result_var", time.time() - t0
    res = ns["result"]
    # build123d Part has .volume; some return Compound
    has_vol = hasattr(res, "volume")
    if not has_vol:
        return False, f"result_type={type(res).__name__}", time.time() - t0
    try:
        v = res.volume
        if v <= 0:
            return False, f"zero_volume", time.time() - t0
    except Exception as e:
        return False, f"volume_check: {type(e).__name__}: {e}", time.time() - t0
    return True, "", time.time() - t0


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
        n_in = n_attempted = n_ok = 0
        err_hist: dict[str, int] = {}
        t0 = time.time()
        with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                n_in += 1
                if not row.get("transpile_ok"):
                    row["b123d_ok"] = False
                    row["b123d_error"] = ""
                    fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                    continue
                n_attempted += 1
                ok, err, dt = validate(row["b123d_code"])
                row["b123d_ok"] = ok
                row["b123d_error"] = err
                row["b123d_validate_s"] = round(dt, 3)
                if ok:
                    n_ok += 1
                else:
                    bucket = err.split(":", 1)[0]
                    err_hist[bucket] = err_hist.get(bucket, 0) + 1
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
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
