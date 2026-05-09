"""Phase 7: Combine prompts/<split>.jsonl + raw/<split>.jsonl -> dataset/<split>.jsonl.

Output schema (one JSON object per line):
{
  "messages": [
    {"role": "system", "content": "<system prompt>"},
    {"role": "user",   "content": "<engineering prompt>"},
    {"role": "assistant", "content": "<CadQuery code block>"}
  ],
  "meta": {
    "uuid": "...",
    "split": "train|validation|test",
    "source": "ADSKAILab/Zero-To-CAD-100k",
    "language": "cadquery",
    "num_faces": int,
    "ops_count": int,
    "score": float,
    "image_path": "images/<uuid>.png",
    "prompt_voice": "...",
    "features": {...}
  }
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw"
PROMPTS_DIR = ROOT / "prompts"
OUT_DIR = ROOT / "dataset"

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI Mechanical Design Copilot. "
    "Given an engineering description of a part, write valid CadQuery 2 Python "
    "code that produces the requested geometry. Use parametric variables where "
    "appropriate, and return the final solid in a variable named `result`."
)


def load_raw_index(split: str) -> dict[str, dict]:
    p = RAW_DIR / f"{split}.jsonl"
    idx: dict[str, dict] = {}
    if not p.exists():
        return idx
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                idx[row["uuid"]] = row
            except Exception:
                continue
    return idx


def pack_split(split: str) -> dict:
    raw = load_raw_index(split)
    prompts_path = PROMPTS_DIR / f"{split}.jsonl"
    out_path = OUT_DIR / f"{split}.jsonl"
    if not prompts_path.exists():
        return {"split": split, "skipped": True, "reason": "no prompts file"}

    n_in, n_out, n_missing_code = 0, 0, 0
    with prompts_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            n_in += 1
            row = json.loads(line)
            uuid = row["uuid"]
            raw_row = raw.get(uuid)
            if not raw_row or not raw_row.get("code"):
                n_missing_code += 1
                continue
            code = raw_row["code"].strip()
            assistant = f"```python\n{code}\n```"
            record = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": row["prompt"]},
                    {"role": "assistant", "content": assistant},
                ],
                "meta": {
                    "uuid": uuid,
                    "split": row["split"],
                    "source": "ADSKAILab/Zero-To-CAD-100k",
                    "language": "cadquery",
                    "num_faces": row["num_faces"],
                    "ops_count": row["ops_count"],
                    "score": row["score"],
                    "image_path": row["image_path"],
                    "prompt_voice": row["prompt_voice"],
                    "features": row["features"],
                },
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_out += 1
    return {
        "split": split,
        "in": n_in,
        "out": n_out,
        "missing_code": n_missing_code,
        "out_path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = sys.argv[1:] or ["train", "validation", "test"]
    results = [pack_split(s) for s in splits]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
