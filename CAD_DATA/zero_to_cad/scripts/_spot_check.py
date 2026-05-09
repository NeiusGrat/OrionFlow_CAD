import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
random.seed(42)

p = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\dataset\train.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
print(f"train rows: {len(rows)}")

# Voice histogram
voices = {}
for r in rows:
    v = r["meta"]["prompt_voice"]
    voices[v] = voices.get(v, 0) + 1
print(f"voice distribution: {voices}")
print()

# Pull 5 random samples and show full structure
samples = random.sample(rows, 5)
for i, r in enumerate(samples):
    m = r["meta"]
    print(f"=== sample {i+1}/5 uuid={m['uuid'][:8]} faces={m['num_faces']} ops={m['ops_count']} voice={m['prompt_voice']} ===")
    print(f"USER: {r['messages'][1]['content']}")
    print(f"ASSISTANT (first 250 chars):")
    print(r['messages'][2]['content'][:250].replace('\n', ' \\n '))
    print()
