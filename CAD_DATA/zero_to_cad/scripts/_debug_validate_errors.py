"""Show 10 examples of ValueError so we know what's breaking."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad")
rows = [json.loads(l) for l in (ROOT / "b123d_validated" / "validation.jsonl").open(encoding="utf-8")]

errs = [r for r in rows if r.get("transpile_ok") and r.get("b123d_error", "").startswith("ValueError")]
print(f"ValueError count: {len(errs)}\n")
for r in errs[:8]:
    print(f"--- uuid={r['uuid'][:8]} ---")
    print(f"ERROR: {r['b123d_error']}")
    print(r["b123d_code"])
    print()
