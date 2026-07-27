#!/usr/bin/env bash
# Bring up an MI300X droplet for the OrionFlow fine-tune, then smoke-test it.
#
# Target image: AMD "Unsloth Studio 2026.7.5 on ROCm 7.2.4, Ubuntu 24.04".
#
# What that image actually is (worth knowing before you go looking):
# Unsloth Studio is a *web app* served on port 80, not a library installed into
# the system Python. `/usr/bin/python3` has no torch at all. The real stack is a
# uv-managed venv, and everything below runs through it. The image also does NOT
# include vLLM, so serving goes through fine_tuning/serve_openai.py.
#
#   scp -r data/forge/sft_v1 fine_tuning root@<droplet>:/root/orionflow/
#   ssh root@<droplet> 'bash /root/orionflow/fine_tuning/setup_droplet.sh'
#
# Run the smoke test to completion before the real run. Environment faults
# surface here in ten minutes instead of at hour twenty.

set -euo pipefail

ROOT="${ORIONFLOW_ROOT:-/root/orionflow}"
MODEL="${ORIONFLOW_MODEL:-Qwen/Qwen3-32B}"
DATA="${ROOT}/sft_v1"
PY="${ORIONFLOW_PY:-/root/.unsloth/studio/unsloth_studio/bin/python}"

echo "==> GPU"
rocm-smi --showproductname || { echo "no ROCm runtime — wrong image?"; exit 1; }

echo "==> interpreter"
test -x "${PY}" || { echo "unsloth venv not at ${PY}; find it with:
  ls -l /proc/\$(pgrep -f 'unsloth studio' | head -1)/exe"; exit 1; }
"${PY}" - <<'PY'
import torch
assert torch.cuda.is_available(), "torch cannot see the GPU"
print("torch", torch.__version__, "| HIP", torch.version.hip)
p = torch.cuda.get_device_properties(0)
print(f"  {p.name}  {p.total_memory/2**30:.0f} GiB")
for m in ("unsloth", "trl", "transformers", "peft"):
    mod = __import__(m); print(f"  {m:13s} {getattr(mod,'__version__','?')}")
PY

echo "==> data"
test -f "${DATA}/train.jsonl" || { echo "missing ${DATA}/train.jsonl — scp it up"; exit 1; }
wc -l "${DATA}"/*.jsonl

echo "==> fetch base weights (~61 GB, cached under ~/.cache/huggingface)"
"${PY}" - <<PY
from huggingface_hub import snapshot_download
snapshot_download("${MODEL}",
                  allow_patterns=["*.safetensors","*.json","*.txt","*.model"],
                  max_workers=8)
print("weights cached")
PY

echo "==> tokenizer sanity: real token lengths against the sequence budget"
"${PY}" - <<PY
import json
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("${MODEL}")
S, E = "<|im_start|>", "<|im_end|>"
def full(m):
    return (f"{S}system\n{m[0]['content']}{E}\n{S}user\n{m[1]['content']}{E}\n"
            f"{S}assistant\n{m[2]['content']}{E}")
rows = [json.loads(l) for l in open("${DATA}/train.jsonl", encoding="utf-8")][:600]
lens = sorted(len(tok(full(r["messages"])).input_ids) for r in rows)
n = len(lens)
print(f"tokens p50={lens[n//2]} p90={lens[int(n*.9)]} p99={lens[int(n*.99)]} max={lens[-1]}")
print(f"over 3072: {sum(1 for x in lens if x > 3072)}/{n}")
print(f"eos={tok.eos_token!r} pad={tok.pad_token!r}")
PY

echo "==> SMOKE TRAIN (400 samples, 1 epoch)"
"${PY}" "${ROOT}/fine_tuning/train_orionflow.py" \
  --model "${MODEL}" --data-dir "${DATA}" \
  --max-samples 400 --epochs 1 --eval-samples 8 --save-steps 100 \
  --out "${ROOT}/runs/smoke"

cat <<'EOF'

==> smoke train finished. Confirm from the log above:
      * "mask check: N/M tokens supervised" and the first supervised tokens
        begin with "<think>" — that proves the prompt is masked out
      * loss is falling and is NOT nan
      * no OutOfMemoryError. If there is one, halve --batch-size and double
        --grad-accum (the effective batch is what matters, and group_by_length
        deliberately puts the longest samples in one batch, so the peak step is
        well above the average one).

    real run (~11 h for one epoch at ~25 s/step, 1471 steps):
      setsid nohup PY train_orionflow.py --data-dir sft_v1 --epochs 1 \
        --save-steps 200 --eval-samples 64 --out runs/orionflow-32b \
        < /dev/null > train.log 2>&1 &

    score a checkpoint (generate here, verify where FreeCAD is):
      PY fine_tuning/generate_batch.py --adapter runs/orionflow-32b/checkpoint-N \
        --data sft_v1/test.jsonl --n 200 --out completions.jsonl
      # then, locally:
      python -m orion.eval_blueprint --completions completions.jsonl

    serve for the demo (no vLLM on this image):
      PY fine_tuning/serve_openai.py --adapter runs/orionflow-32b --port 8000
EOF
