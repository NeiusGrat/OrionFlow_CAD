"""Show successful + 5 failures to understand transpile gaps."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad")
b123d = list((ROOT / "b123d" / "validation.jsonl").open(encoding="utf-8"))
raw = {}
for line in (ROOT / "raw" / "validation.jsonl").open(encoding="utf-8"):
    r = json.loads(line)
    raw[r["uuid"]] = r["code"]

oks = [json.loads(l) for l in b123d if json.loads(l)["transpile_ok"]]
fails = [json.loads(l) for l in b123d if not json.loads(l)["transpile_ok"]]

print(f"OK={len(oks)}  FAIL={len(fails)}")
print()
print("===== 3 SUCCESSFUL EXAMPLES =====")
for r in oks[:3]:
    print(f"\n--- uuid={r['uuid'][:8]} ---")
    print("ORIGINAL CADQUERY:")
    print(raw[r["uuid"]][:600])
    print("TRANSPILED B123D:")
    print(r["b123d_code"])
    print()

print("===== 5 FAILED EXAMPLES (diverse reasons) =====")
seen_reasons = set()
for r in fails:
    reason_bucket = r["reason"].split(":", 1)[0]
    if reason_bucket in seen_reasons:
        continue
    seen_reasons.add(reason_bucket)
    if len(seen_reasons) > 6:
        break
    print(f"\n--- uuid={r['uuid'][:8]}  reason: {r['reason']} ---")
    print(raw[r["uuid"]][:700])
    print("...")
