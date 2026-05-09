import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\dataset_final\train.jsonl")

b_rows = []
cq_rows = []
for line in p.open(encoding="utf-8"):
    r = json.loads(line)
    if r["meta"].get("transpile_ok"):
        b_rows.append(r)
    else:
        cq_rows.append(r)
    if len(b_rows) >= 3 and len(cq_rows) >= 1:
        break

print(f"Found build123d: {len(b_rows)}, cadquery: {len(cq_rows)}\n")
for i, r in enumerate(b_rows[:2]):
    m = r["meta"]
    print(f"=== B123D #{i+1} uuid={m['uuid'][:8]} faces={m['num_faces']} ===")
    print(f"USER PROMPT: {r['messages'][1]['content']}")
    print(f"ASSISTANT (b123d):")
    print(r['messages'][2]['content'])
    print()
    print(f"meta.language: {m['language']}, transpile_ok: {m['transpile_ok']}")
    print(f"meta.cadquery_code (original, first 200 chars):")
    print(m['cadquery_code'][:200])
    print()

if cq_rows:
    r = cq_rows[0]
    print(f"=== CQ FALLBACK uuid={r['meta']['uuid'][:8]} ===")
    print(f"meta.language: {r['meta']['language']}")
    print(f"meta.transpile_ok: {r['meta']['transpile_ok']}")
    print(f"meta.transpile_skip_reason: {r['meta'].get('transpile_skip_reason', '-')}")
    print(f"USER: {r['messages'][1]['content']}")
    print(f"ASSISTANT (first 200 chars): {r['messages'][2]['content'][:200]}")
