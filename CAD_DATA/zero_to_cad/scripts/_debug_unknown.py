"""Histogram of unknown op names from failures."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad")
b123d = [json.loads(l) for l in (ROOT / "b123d" / "validation.jsonl").open(encoding="utf-8")]

unknown = Counter()
for r in b123d:
    if r["reason"].startswith("unknown op"):
        op = r["reason"].split(":", 1)[1].strip()
        unknown[op] += 1
print("Unknown op histogram (top 20):")
for op, n in unknown.most_common(20):
    print(f"  {op}: {n}")
