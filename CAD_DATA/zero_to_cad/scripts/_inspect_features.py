import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\analyzed\train.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
print(f"total: {len(rows)}")
print()
for i in [0, 5, 10, 25, 100, 500, 1000]:
    if i >= len(rows):
        continue
    r = rows[i]
    f = r["features"]
    print(f"=== #{i} uuid={r['uuid'][:8]} faces={r['num_faces']} ops={r['ops_count']} ===")
    print(f"  base_solid: {f['base_solid']}  base_dims: {f['base_dims']}")
    print(f"  dims ({len(f['dims'])}): {dict(list(f['dims'].items())[:6])}{'...' if len(f['dims'])>6 else ''}")
    print(f"  op_counts: {f['op_counts']}")
    print(f"  holes: {f['holes']}  edges: {f['edges']}")
    print(f"  pockets={f['pockets']} extrusions={f['extrusions']} revs={f['revolutions']} multi_body={f['multi_body']} cuts={f['cuts']} profiles={f['custom_profiles']}")
    print(f"  selectors: {f['selectors']}")
    print()
