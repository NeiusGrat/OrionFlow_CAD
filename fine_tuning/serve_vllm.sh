#!/usr/bin/env bash
#
# Serve the fine-tuned OrionFlow model from an AMD MI300X droplet.
#
# Target: DigitalOcean/AMD "vLLM on ROCm" quick-start image, MI300X x1. One
# card has 192 GB of VRAM; Qwen3-32B in bf16 is ~64 GB, so the whole model plus
# a large KV cache fits on a single GPU. There is no reason to rent x8 for this.
#
# The LoRA is attached at serve time rather than merged: the adapter is 2.1 GB
# against 64 GB for a merged copy, and vLLM swaps it in with no measurable
# latency cost.
#
# Usage (on the droplet):
#     export HF_TOKEN=hf_...            # the LoRA repo is private
#     export ORION_SERVE_KEY=...        # bearer token clients must present
#     bash fine_tuning/serve_vllm.sh
#
# Then point the studio at it:
#     ORION_LLM_PROVIDER=vllm
#     ORION_LLM_BASE_URL=http://<droplet-ip>:8000/v1
#     ORION_LLM_API_KEY=$ORION_SERVE_KEY
#     ORION_LLM_MODEL=orionflow
#
set -euo pipefail

BASE_MODEL="${ORION_BASE_MODEL:-Qwen/Qwen3-32B}"
LORA_REPO="${ORION_LORA_REPO:-sahilmaniyar888/orionflow-cad-qwen3-32b-lora}"
# v2 lives in a subfolder; v1 is at the repo root. v2 is the one to serve —
# its headline VERIFIED is 1.3 points lower but it scores 58% on free-form
# prose against v1's 50%, and prose is what a person types at a live demo.
LORA_SUBDIR="${ORION_LORA_SUBDIR:-v2}"
LORA_DIR="${ORION_LORA_DIR:-/root/orionflow/lora}"
PORT="${ORION_SERVE_PORT:-8000}"
# Trained at 3072. Serving longer is fine for the conversation role, but the
# Blueprint role should stay near the training length — see max_tokens in the
# harness config rather than stretching this.
MAX_LEN="${ORION_SERVE_MAX_LEN:-8192}"
GPU_UTIL="${ORION_SERVE_GPU_UTIL:-0.90}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/orionflow_chatml.jinja"

# ---------------------------------------------------------------- preflight --
if [[ -z "${HF_TOKEN:-}" ]]; then
    echo "FATAL: HF_TOKEN is unset. $LORA_REPO is private and cannot be pulled." >&2
    exit 1
fi
if [[ -z "${ORION_SERVE_KEY:-}" ]]; then
    echo "FATAL: ORION_SERVE_KEY is unset. Refusing to expose an unauthenticated" >&2
    echo "       32B model on a public IP. Generate one:  openssl rand -hex 32" >&2
    exit 1
fi
if [[ ! -f "$TEMPLATE" ]]; then
    echo "FATAL: $TEMPLATE is missing." >&2
    echo "       Serving without it silently falls back to Qwen3's packaged" >&2
    echo "       template, which rewrites the assistant turn — the model stops" >&2
    echo "       matching the one that scored 94%. Copy the whole fine_tuning/" >&2
    echo "       directory, or clone the repo on this box." >&2
    exit 1
fi

command -v rocm-smi >/dev/null 2>&1 && rocm-smi --showproductname || \
    echo "WARNING: rocm-smi not found; is this really a ROCm image?" >&2

echo "==> base model : $BASE_MODEL"
echo "==> lora       : $LORA_REPO ($LORA_SUBDIR)"
echo "==> template   : $TEMPLATE"

# ----------------------------------------------------------------- download --
pip install --quiet --upgrade "huggingface_hub[cli]" >/dev/null 2>&1 || true

echo "==> pulling LoRA adapter"
hf download "$LORA_REPO" --local-dir "$LORA_DIR" --token "$HF_TOKEN"

ADAPTER="$LORA_DIR/$LORA_SUBDIR"
[[ -n "$LORA_SUBDIR" ]] || ADAPTER="$LORA_DIR"
if [[ ! -f "$ADAPTER/adapter_config.json" ]]; then
    echo "FATAL: no adapter_config.json under $ADAPTER" >&2
    echo "       Contents:" >&2
    ls -la "$ADAPTER" >&2 || true
    exit 1
fi

# vLLM refuses to load an adapter whose rank exceeds --max-lora-rank, and the
# error names neither number. Read it from the adapter and pass it through.
LORA_RANK="$(python3 -c "import json;print(json.load(open('$ADAPTER/adapter_config.json'))['r'])")"
echo "==> adapter rank: $LORA_RANK"

echo "==> pulling base model (~64 GB, first run only)"
hf download "$BASE_MODEL" --token "$HF_TOKEN"

# -------------------------------------------------------------------- serve --
# Requests address the fine-tuned model as "orionflow"; the untouched base
# stays reachable as "orionflow-base" so a regression can be A/B'd against it
# without a second deploy.
echo "==> starting vLLM on :$PORT"
exec vllm serve "$BASE_MODEL" \
    --served-model-name orionflow-base \
    --enable-lora \
    --lora-modules "orionflow=$ADAPTER" \
    --max-lora-rank "$LORA_RANK" \
    --max-loras 1 \
    --chat-template "$TEMPLATE" \
    --dtype bfloat16 \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --api-key "$ORION_SERVE_KEY"
