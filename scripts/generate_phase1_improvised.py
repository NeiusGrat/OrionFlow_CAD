"""Rebuild a stricter Phase 1 dataset with clean formatting and safer edits.

This script reads the validated upstream train/val/test splits and writes a new
`phase1_improvised.jsonl` file under `data/phase1_5k/`.

Key differences from the original Phase 1 builder:
- strips assistant prose/code fences so assistant content is raw code only
- drops DeepCAD-derived samples for Phase 1 quality
- enforces no-new-variables on edit samples
- enforces stricter structure preservation for param-change and add-feature edits
- drops samples with validation warnings
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_FILES = [
    ROOT / "data" / "final_training_dataset" / "train.jsonl",
    ROOT / "data" / "final_training_dataset" / "val.jsonl",
    ROOT / "data" / "final_training_dataset" / "test.jsonl",
]
OUTPUT_DIR = ROOT / "data" / "phase1_5k"
OUTPUT_PATH = OUTPUT_DIR / "phase1_improvised.jsonl"

TARGET_TOTAL = 5000
TARGET_EDITS = 3000
TARGET_GENS = 2000
TARGET_PARAM_EDITS = 2300
TARGET_ADD_EDITS = 700
TARGET_COMPLEX_GENS = 311
TARGET_TEMPLATE_GENS = TARGET_GENS - TARGET_COMPLEX_GENS
SEED = 42

DROP_SOURCES = {"deepcad", "deepcad_edit_param", "deepcad_edit_add"}
EDIT_SOURCES = {"template_edit_param", "template_edit_add"}
GEN_SOURCES = {"template", "complex_generated"}

CODE_BLOCK_RE = re.compile(r"```python\n(.*?)\n```", re.S)
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)
FEATURE_COMMENT_RE = re.compile(r"^(\s*# Feature )(\d+|N)(:.*)$")
NUMBERED_FEATURE_RE = re.compile(r"^\s*# Feature (\d+):")


def extract_code(text: str) -> str | None:
    match = CODE_BLOCK_RE.search(text)
    if not match:
        return None

    code = match.group(1).strip("\n")
    if not code.startswith("from build123d import *"):
        return None
    if not code.endswith('export_step(result, "output.step")'):
        return None
    if "<think>" in code:
        return None
    return code


def split_sections(code: str) -> tuple[list[str], list[str]]:
    lines = code.splitlines()
    try:
        feature_index = lines.index("# --- Feature Tree ---")
    except ValueError:
        return lines, []
    return lines[:feature_index], lines[feature_index:]


def assignment_names(before_feature_tree: list[str]) -> list[str]:
    names: list[str] = []
    for line in before_feature_tree:
        match = ASSIGNMENT_RE.match(line)
        if match:
            names.append(match.group(1))
    return names


def is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return True

    start = 0
    for line in haystack:
        if line == needle[start]:
            start += 1
            if start == len(needle):
                return True
    return False


def renumber_feature_n(user_code: str, assistant_code: str) -> str:
    if "Feature N:" not in assistant_code:
        return assistant_code

    max_feature = 0
    for line in user_code.splitlines():
        match = NUMBERED_FEATURE_RE.match(line)
        if match:
            max_feature = max(max_feature, int(match.group(1)))

    if max_feature == 0:
        return assistant_code

    replaced = False
    out_lines: list[str] = []
    for line in assistant_code.splitlines():
        match = FEATURE_COMMENT_RE.match(line)
        if match and match.group(2) == "N" and not replaced:
            out_lines.append(f"{match.group(1)}{max_feature + 1}{match.group(3)}")
            replaced = True
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def classify_add_feature(user_text: str) -> str:
    tail = user_text.splitlines()[-1].lower()
    if "fillet" in tail:
        return "fillet"
    if "chamfer" in tail:
        return "chamfer"
    if "hole" in tail:
        return "hole"
    if "cut" in tail or "slot" in tail or "cutout" in tail:
        return "cut"
    return "other"


def clean_record(record: dict) -> dict:
    clone = json.loads(json.dumps(record))
    assistant_msg = next((m for m in clone["messages"] if m.get("role") == "assistant"), None)
    if assistant_msg is None:
        raise ValueError("record missing assistant message")
    assistant_code = extract_code(assistant_msg.get("content", ""))
    if assistant_code is None:
        raise ValueError("assistant code not extractable")
    assistant_msg["content"] = assistant_code
    return clone


def is_clean_param_edit(user_code: str, assistant_code: str) -> bool:
    user_head, user_tail = split_sections(user_code)
    assistant_head, assistant_tail = split_sections(assistant_code)

    if not user_tail or not assistant_tail:
        return False

    if assignment_names(user_head) != assignment_names(assistant_head):
        return False

    if user_tail != assistant_tail:
        return False

    changed_lines = sum(1 for left, right in zip(user_head, assistant_head) if left != right)
    changed_lines += abs(len(user_head) - len(assistant_head))
    return changed_lines >= 1


def is_clean_add_edit(user_code: str, assistant_code: str) -> bool:
    user_head, _ = split_sections(user_code)
    assistant_head, _ = split_sections(assistant_code)

    if assignment_names(user_head) != assignment_names(assistant_head):
        return False

    if user_head != assistant_head:
        return False

    user_lines = user_code.splitlines()
    assistant_lines = assistant_code.splitlines()
    if len(assistant_lines) <= len(user_lines):
        return False

    if not is_subsequence(user_lines, assistant_lines):
        return False

    bad_tokens = (
        "circle_radius_",
        "extrude_depth_",
        "offset_x_",
        "offset_y_",
        "base_width =",
        "base_height =",
        "secondary_width =",
        "secondary_height =",
    )
    return not any(token in assistant_code for token in bad_tokens)


def load_pools() -> tuple[dict[str, list[dict]], Counter]:
    pools: dict[str, list[dict]] = {
        "template_edit_param": [],
        "template_edit_add": [],
        "template": [],
        "complex_generated": [],
    }
    stats = Counter()

    for path in INPUT_FILES:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                validation = record.get("_validation", {})
                source = record.get("source", "")

                stats["seen"] += 1

                if not validation.get("passed") or validation.get("stage_failed"):
                    stats["drop_invalid"] += 1
                    continue

                if source.startswith("phase5") or source == "synthetic_refusal":
                    stats["drop_refusal"] += 1
                    continue

                if source in DROP_SOURCES:
                    stats["drop_deepcad"] += 1
                    continue

                if source not in EDIT_SOURCES | GEN_SOURCES:
                    stats["drop_other_source"] += 1
                    continue

                if validation.get("warnings"):
                    stats["drop_warning"] += 1
                    continue

                try:
                    cleaned = clean_record(record)
                except ValueError:
                    stats["drop_format"] += 1
                    continue

                messages = cleaned["messages"]
                user_text = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
                assistant_code = next((m.get("content", "") for m in messages if m.get("role") == "assistant"), "")

                if source == "template_edit_param":
                    user_code = extract_code(user_text)
                    if user_code is None or not is_clean_param_edit(user_code, assistant_code):
                        stats["drop_param_edit"] += 1
                        continue
                    pools[source].append(cleaned)
                    stats["keep_template_edit_param"] += 1
                    continue

                if source == "template_edit_add":
                    user_code = extract_code(user_text)
                    if user_code is None or not is_clean_add_edit(user_code, assistant_code):
                        stats["drop_add_edit"] += 1
                        continue
                    assistant_msg = next(m for m in cleaned["messages"] if m.get("role") == "assistant")
                    assistant_msg["content"] = renumber_feature_n(user_code, assistant_msg["content"])
                    cleaned["add_feature_kind"] = classify_add_feature(user_text)
                    pools[source].append(cleaned)
                    stats["keep_template_edit_add"] += 1
                    continue

                pools[source].append(cleaned)
                stats[f"keep_{source}"] += 1

    return pools, stats


def sample_records(records: list[dict], count: int, rng: random.Random) -> list[dict]:
    if count >= len(records):
        chosen = list(records)
        rng.shuffle(chosen)
        return chosen
    chosen = list(records)
    rng.shuffle(chosen)
    return chosen[:count]


def sample_add_feature_records(records: list[dict], count: int, rng: random.Random) -> list[dict]:
    buckets: dict[str, list[dict]] = {"fillet": [], "chamfer": [], "cut": [], "hole": [], "other": []}
    for record in records:
        buckets[record.get("add_feature_kind", "other")].append(record)

    for group in buckets.values():
        rng.shuffle(group)

    ordered_kinds = ["hole", "cut", "other", "fillet", "chamfer"]
    selected: list[dict] = []

    for kind in ordered_kinds:
        if len(selected) >= count:
            break
        want = min(len(buckets[kind]), max(1, count // len(ordered_kinds)))
        selected.extend(buckets[kind][:want])
        buckets[kind] = buckets[kind][want:]

    remaining: list[dict] = []
    for kind in ordered_kinds:
        remaining.extend(buckets[kind])
    rng.shuffle(remaining)

    need = count - len(selected)
    if need > 0:
        selected.extend(remaining[:need])

    return selected[:count]


def build_dataset() -> tuple[list[dict], Counter]:
    rng = random.Random(SEED)
    pools, stats = load_pools()

    param_records = sample_records(pools["template_edit_param"], TARGET_PARAM_EDITS, rng)
    add_records = sample_add_feature_records(pools["template_edit_add"], TARGET_ADD_EDITS, rng)
    complex_records = sample_records(pools["complex_generated"], TARGET_COMPLEX_GENS, rng)
    template_gen_records = sample_records(pools["template"], TARGET_TEMPLATE_GENS, rng)

    selected = param_records + add_records + complex_records + template_gen_records
    rng.shuffle(selected)

    stats["selected_param_edits"] = len(param_records)
    stats["selected_add_edits"] = len(add_records)
    stats["selected_complex_gens"] = len(complex_records)
    stats["selected_template_gens"] = len(template_gen_records)
    stats["selected_total"] = len(selected)
    stats["selected_edits"] = len(param_records) + len(add_records)
    stats["selected_gens"] = len(complex_records) + len(template_gen_records)

    if stats["selected_total"] != TARGET_TOTAL:
        raise RuntimeError(f"expected {TARGET_TOTAL} records, found {stats['selected_total']}")
    if stats["selected_edits"] != TARGET_EDITS:
        raise RuntimeError(f"expected {TARGET_EDITS} edits, found {stats['selected_edits']}")
    if stats["selected_gens"] != TARGET_GENS:
        raise RuntimeError(f"expected {TARGET_GENS} generations, found {stats['selected_gens']}")

    return selected, stats


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dataset, stats = build_dataset()

    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        for record in dataset:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    print(f"Wrote {len(dataset)} records to {OUTPUT_PATH}")
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
