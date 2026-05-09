import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\raw\train.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
print(f"total rows: {len(rows)}")
for i in [0, 5, 10, 15]:
    r = rows[i]
    print("=" * 70)
    print(f"#{i} uuid={r['uuid'][:8]}  faces={r['num_faces']}  ops={r['ops_count']}")
    print("--- code ---")
    print(r["code"][:1400])
    print("--- ops_json (first 1000 chars) ---")
    print(r["ops_json"][:1000])
