"""Back the trained adapter up to a PRIVATE HF model repo.

Token is read from stdin so it never appears in argv or the process table.
Only the LoRA adapter is uploaded (~2.1 GB) — the 62 GB merged model is
reproducible from Qwen3-32B plus this adapter, so shipping it would be waste.
"""
import sys, os, json
from huggingface_hub import HfApi

token = sys.stdin.readline().strip()
assert token.startswith("hf_"), "no token on stdin"

REPO = "sahilmaniyar888/orionflow-cad-qwen3-32b-lora"
SRC = "/root/orionflow/runs/orionflow-32b"

card = """---
license: apache-2.0
base_model: Qwen/Qwen3-32B
library_name: peft
tags: [cad, text-to-cad, freecad, parametric, lora]
---

# OrionFlow CAD — Qwen3-32B LoRA

Emits a **parametric Blueprint** (named variables + a feature tree whose every
dimension is an expression, never a literal) that compiles to a FreeCAD model
and is verified against its own closed-form assertions.

## Results (300 held-out test topologies, unseen in any parametrization)

| metric | untrained | this adapter |
|---|---|---|
| VERIFIED (builds + matches its own predicted volume) | 0% | **95.3%** |
| VERIFIED @1 repair | — | 96.3% |
| built in FreeCAD | — | 98.3% |
| prompt with all variables given | — | 98.8% |
| prose prompt, model chooses dimensions | — | 91.2% |
| volume rel_err (median) | — | 1.94e-16 |

Trained 1 epoch (1471 steps) on 23,532 verified samples, LoRA r=64 alpha=128,
bf16, single MI300X.

**Note:** eval loss rose monotonically (0.0634 -> 0.0691) over the same steps
where VERIFIED rose 75% -> 95.3%. Early-stopping on validation loss would have
shipped the 75% model.

**Known limitation:** the model derives volumes correctly *symbolically* but
does not evaluate them — a stated numeric volume in its reasoning should be
recomputed from its expression, not trusted.
"""

api = HfApi(token=token)
api.create_repo(REPO, repo_type="model", private=True, exist_ok=True)
with open("/tmp/README.md", "w", encoding="utf-8") as f:
    f.write(card)

files = ["adapter_model.safetensors", "adapter_config.json",
         "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
         "added_tokens.json", "vocab.json"]
for fn in files:
    p = os.path.join(SRC, fn)
    if os.path.exists(p):
        api.upload_file(path_or_fileobj=p, path_in_repo=fn, repo_id=REPO,
                        repo_type="model")
        print("uploaded", fn, f"{os.path.getsize(p)/2**20:.0f} MB")
api.upload_file(path_or_fileobj="/tmp/README.md", path_in_repo="README.md",
                repo_id=REPO, repo_type="model")
print("uploaded README.md")
print("DONE ->", REPO)
