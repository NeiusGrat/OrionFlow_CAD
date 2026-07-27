"""Back the v2 adapter up to the same private HF repo, under a subfolder.

Token from stdin only — never argv, never source. v1 stays at the repo root so
existing references keep working; v2 lands in v2/ alongside it.
"""
import os
import sys
from huggingface_hub import HfApi

token = sys.stdin.readline().strip()
assert token.startswith("hf_"), "no token on stdin"

REPO = "sahilmaniyar888/orionflow-cad-qwen3-32b-lora"
SRC = "/root/orionflow/runs/orionflow-32b-v2"

api = HfApi(token=token)
files = ["adapter_model.safetensors", "adapter_config.json",
         "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
         "added_tokens.json", "vocab.json"]
for fn in files:
    p = os.path.join(SRC, fn)
    if os.path.exists(p):
        api.upload_file(path_or_fileobj=p, path_in_repo=f"v2/{fn}",
                        repo_id=REPO, repo_type="model")
        print("uploaded v2/%s  %.0f MB" % (fn, os.path.getsize(p) / 2**20))
print("DONE")
