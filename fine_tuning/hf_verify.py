"""Verify the adapter backup. Token from stdin only — never argv, never source."""
import sys
from huggingface_hub import HfApi

token = sys.stdin.readline().strip()
api = HfApi(token=token)
info = api.model_info("sahilmaniyar888/orionflow-cad-qwen3-32b-lora",
                      files_metadata=True)
print("repo:", info.id, "| private:", info.private)
total = 0
for f in sorted(info.siblings, key=lambda x: -(x.size or 0)):
    if f.size:
        total += f.size
        print(f"  {f.rfilename:32s} {f.size/2**20:8.1f} MB")
print(f"  {'TOTAL':32s} {total/2**20:8.1f} MB")
