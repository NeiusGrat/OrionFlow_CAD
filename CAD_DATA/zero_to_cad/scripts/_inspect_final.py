import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\dataset\train.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
print(f"total: {len(rows)}\n")
r = rows[0]
print("keys:", list(r.keys()))
print("messages roles:", [m["role"] for m in r["messages"]])
print()
print("=== SYSTEM ===")
print(r["messages"][0]["content"])
print()
print("=== USER ===")
print(r["messages"][1]["content"])
print()
print("=== ASSISTANT (first 600 chars) ===")
print(r["messages"][2]["content"][:600])
print()
print("=== META ===")
print(json.dumps(r["meta"], indent=2)[:600])
print()
# size summary
total_size = sum(len(json.dumps(rr, ensure_ascii=False).encode("utf-8")) for rr in rows[:100])
avg = total_size / 100
print(f"avg row size (first 100): {avg:.0f} bytes")
