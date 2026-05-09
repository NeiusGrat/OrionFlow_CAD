"""Phase 5c: Final dataset packer.

For each existing dataset/<split>.jsonl row, look up b123d_validated result.
If b123d_ok=True: replace assistant message with b123d code and adjust
system prompt; move CadQuery code into meta.cadquery_code.

Writes dataset_final/<split>.jsonl alongside the original dataset/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"
B123D_DIR = ROOT / "b123d_validated"
OUT_DIR = ROOT / "dataset_final"

SYSTEM_CADQUERY = (
    "You are OrionFlow, an AI Mechanical Design Copilot. "
    "Given an engineering description of a part, write valid CadQuery 2 Python "
    "code that produces the requested geometry. Use parametric variables where "
    "appropriate, and return the final solid in a variable named `result`."
)
SYSTEM_BUILD123D = (
    "You are OrionFlow, an AI Mechanical Design Copilot. "
    "Given an engineering description of a part, write valid build123d Python "
    "code that produces the requested geometry. Use the BuildPart context "
    "manager, parametric variables, and bind the final solid to `result`."
)


def load_b123d_index(split: str) -> dict[str, dict]:
    p = B123D_DIR / f"{split}.jsonl"
    idx: dict[str, dict] = {}
    if not p.exists():
        return idx
    with p.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            idx[row["uuid"]] = row
    return idx


def pack(split: str) -> dict:
    in_path = DATASET_DIR / f"{split}.jsonl"
    if not in_path.exists():
        return {"split": split, "skipped": True}
    out_path = OUT_DIR / f"{split}.jsonl"
    b123d_idx = load_b123d_index(split)

    n = 0
    n_b123d = 0
    n_cq = 0
    with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            n += 1
            uuid = row["meta"]["uuid"]
            b = b123d_idx.get(uuid, {})
            cq_code = row["messages"][2]["content"]  # ```python\n...\n```

            if b.get("b123d_ok"):
                # Replace assistant with b123d code
                b_code = b["b123d_code"].strip()
                row["messages"][0]["content"] = SYSTEM_BUILD123D
                row["messages"][2]["content"] = f"```python\n{b_code}\n```"
                row["meta"]["language"] = "build123d"
                row["meta"]["transpile_ok"] = True
                row["meta"]["cadquery_code"] = cq_code
                n_b123d += 1
            else:
                # Keep CQ as assistant
                row["meta"]["transpile_ok"] = False
                if b.get("transpile_ok") is True and not b.get("b123d_ok"):
                    row["meta"]["transpile_validate_error"] = b.get("b123d_error", "")
                elif b.get("reason"):
                    row["meta"]["transpile_skip_reason"] = b.get("reason")
                n_cq += 1

            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "split": split,
        "rows": n,
        "build123d_rows": n_b123d,
        "cadquery_rows": n_cq,
        "b123d_pct": round(100 * n_b123d / max(1, n), 2),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = sys.argv[1:] or ["train", "validation", "test"]
    summary = [pack(s) for s in splits]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
