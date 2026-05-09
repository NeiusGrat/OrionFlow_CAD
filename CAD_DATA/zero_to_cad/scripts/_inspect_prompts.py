import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\prompts\train.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
print(f"total: {len(rows)}\n")

# Show 25 varied samples spread out
indices = list(range(0, len(rows), max(1, len(rows) // 25)))[:25]
for i in indices:
    r = rows[i]
    f = r["features"]
    print(f"#{i:5d}  voice={r['prompt_voice']:18s}  faces={r['num_faces']:3d} ops={r['ops_count']:2d}  base={f['base_solid']}")
    print(f"  CATEGORY: dims={list(f['dims'].keys())[:5]}")
    print(f"  PROMPT  : {r['prompt']}")
    print()
