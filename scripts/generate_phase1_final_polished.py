"""Build the final polished Phase 1 dataset.

Goals:
- preserve the safe formatting and minimal-diff behavior from phase1_improvised
- prune weak generation samples
- add a clean hole-edit slice with no new parameters
- populate geometry metrics for every retained sample
"""

from __future__ import annotations

import gc
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_FILES = [
    ROOT / "data" / "final_training_dataset" / "train.jsonl",
    ROOT / "data" / "final_training_dataset" / "val.jsonl",
    ROOT / "data" / "final_training_dataset" / "test.jsonl",
]
OUTPUT_DIR = ROOT / "data" / "phase1_5k"
OUTPUT_PATH = OUTPUT_DIR / "phase1_final_polished.jsonl"

TARGET_TOTAL = 5000
TARGET_GENS = 2000
TARGET_PARAM_EDITS = 2300
TARGET_FILLET_CHAMFER_EDITS = 0
TARGET_HOLE_EDITS = 700
SEED = 42

DROP_SOURCES = {"deepcad", "deepcad_edit_param", "deepcad_edit_add"}
EDIT_SOURCES = {"template_edit_param", "template_edit_add"}
GEN_SOURCES = {"template"}
GEN_TEMPLATE_BLACKLIST = {"gusset_bracket"}

SYSTEM_PROMPT_EDIT = (
    "You are OrionFlow, an AI mechanical design copilot. The user will show "
    "you existing Build123d code and request a modification. Generate the "
    "complete modified code preserving the Feature Tree Convention structure. "
    "Only change what the user requested."
)

CODE_BLOCK_RE = re.compile(r"```python\n(.*?)\n```", re.S)
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)
FEATURE_COMMENT_RE = re.compile(r"^(\s*# Feature )(\d+|N)(:.*)$")
NUMBERED_FEATURE_RE = re.compile(r"^\s*# Feature (\d+):")


def deep_copy(record: dict) -> dict:
    return json.loads(json.dumps(record))


def stripped_code_hash(code: str) -> str:
    normalized = "\n".join(
        line.rstrip() for line in code.strip().splitlines() if line.strip()
    )
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


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
    return [
        match.group(1)
        for line in before_feature_tree
        if (match := ASSIGNMENT_RE.match(line))
    ]


def is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return True

    idx = 0
    for line in haystack:
        if line == needle[idx]:
            idx += 1
            if idx == len(needle):
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
    clone = deep_copy(record)
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


def generation_quality_ok(record: dict, code: str) -> bool:
    template = record.get("template")
    if template in GEN_TEMPLATE_BLACKLIST:
        return False
    if "Rectangle(width, width)" in code:
        return False
    if "Rectangle(height, height)" in code:
        return False
    return True


def load_base_pools() -> tuple[dict[str, list[dict]], Counter]:
    pools: dict[str, list[dict]] = {
        "template_edit_param": [],
        "template_edit_add": [],
        "template": [],
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

                assistant_code = next(
                    (m.get("content", "") for m in cleaned["messages"] if m.get("role") == "assistant"),
                    "",
                )

                if source == "template_edit_param":
                    user_code = extract_code(next(
                        (m.get("content", "") for m in cleaned["messages"] if m.get("role") == "user"),
                        "",
                    ))
                    if user_code is None or not is_clean_param_edit(user_code, assistant_code):
                        stats["drop_param_edit"] += 1
                        continue
                    pools[source].append(cleaned)
                    continue

                if source == "template_edit_add":
                    user_text = next(
                        (m.get("content", "") for m in cleaned["messages"] if m.get("role") == "user"),
                        "",
                    )
                    user_code = extract_code(user_text)
                    if user_code is None or not is_clean_add_edit(user_code, assistant_code):
                        stats["drop_add_edit"] += 1
                        continue
                    assistant_msg = next(m for m in cleaned["messages"] if m.get("role") == "assistant")
                    assistant_msg["content"] = renumber_feature_n(user_code, assistant_msg["content"])
                    cleaned["add_feature_kind"] = classify_add_feature(user_text)
                    pools[source].append(cleaned)
                    continue

                if not generation_quality_ok(cleaned, assistant_code):
                    stats["drop_generation_quality"] += 1
                    continue
                pools[source].append(cleaned)

    return pools, stats


def next_feature_number(code: str) -> int:
    max_feature = 0
    for line in code.splitlines():
        match = NUMBERED_FEATURE_RE.match(line)
        if match:
            max_feature = max(max_feature, int(match.group(1)))
    return max_feature + 1


def insert_feature_block(code: str, feature_lines: list[str]) -> str:
    lines = code.splitlines()
    try:
        export_idx = lines.index("# --- Export ---")
    except ValueError as exc:
        raise ValueError("missing export section") from exc
    return "\n".join(lines[:export_idx] + [""] + feature_lines + [""] + lines[export_idx:])


def make_edit_user_prompt(base_code: str, modification: str) -> str:
    return (
        "Here is my current part:\n\n"
        f"```python\n{base_code}\n```\n\n"
        f"Modification: {modification}"
    )


def make_hole_edit_record(base_record: dict, modification: str, code: str, pattern: str) -> dict:
    base_code = next(
        (m.get("content", "") for m in base_record["messages"] if m.get("role") == "assistant"),
        "",
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_EDIT},
            {"role": "user", "content": make_edit_user_prompt(base_code, modification)},
            {"role": "assistant", "content": code},
        ],
        "source": "template_edit_hole_polished",
        "edit_type": "add_feature",
        "base_template": base_record.get("template"),
        "category": base_record.get("category"),
        "complexity": base_record.get("complexity"),
        "params": deep_copy(base_record.get("params", {})),
        "_validation": {
            "passed": False,
            "stage_failed": None,
            "error": None,
            "code_hash": stripped_code_hash(code),
            "geometry_metrics": None,
            "warnings": [],
        },
        "source_bucket": "edit_polished",
        "add_feature_kind": "hole",
        "hole_edit_pattern": pattern,
    }


def hole_candidates_for_record(base_record: dict) -> list[dict]:
    template = base_record.get("template")
    base_code = next(
        (m.get("content", "") for m in base_record["messages"] if m.get("role") == "assistant"),
        "",
    )
    feature_no = next_feature_number(base_code)
    candidates: list[dict] = []

    def add_candidate(modification: str, pattern: str, body_lines: list[str]) -> None:
        feature_lines = [f"    # Feature {feature_no}: {body_lines[0]}"] + body_lines[1:]
        code = insert_feature_block(base_code, feature_lines)
        candidates.append(make_hole_edit_record(base_record, modification, code, pattern))

    if template == "mounting_plate":
        add_candidate(
            "Add a center through-hole using the existing hole_dia size",
            "through_center",
            [
                "Center through-hole using existing hole_dia",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        Circle(hole_dia / 2)",
                "    extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add one offset through-hole on the top face using the existing hole_dia size",
            "through_offset",
            [
                "Offset through-hole using existing hole_dia",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        with Locations((width * 0.22, 0)):",
                "            Circle(hole_dia / 2)",
                "    extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add four inner mounting holes in a 2x2 grid using the existing hole_dia size",
            "through_grid",
            [
                "Inner 2x2 mounting hole grid using existing hole_dia",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        with GridLocations(width * 0.45, height * 0.35, 2, 2):",
                "            Circle(hole_dia / 2)",
                "    extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            ],
        )

    if template == "base_plate":
        add_candidate(
            "Add a center through-hole using the existing hole_dia size",
            "through_center",
            [
                "Center through-hole using existing hole_dia",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        Circle(hole_dia / 2)",
                "    extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add one offset through-hole using the existing hole_dia size",
            "through_offset",
            [
                "Offset through-hole using existing hole_dia",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        with Locations((0, height * 0.2)):",
                "            Circle(hole_dia / 2)",
                "    extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add a shallow center blind hole using the existing cbore_dia and cbore_depth",
            "blind_center",
            [
                "Center blind hole using existing counterbore dimensions",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        Circle(cbore_dia / 2)",
                "    extrude(amount=-cbore_depth, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add one offset blind hole using the existing cbore_dia and cbore_depth",
            "blind_offset",
            [
                "Offset blind hole using existing counterbore dimensions",
                "    with BuildSketch(Plane.XY.offset(thickness)):",
                "        with Locations((0, height * 0.2)):",
                "            Circle(cbore_dia / 2)",
                "    extrude(amount=-cbore_depth, mode=Mode.SUBTRACT)",
            ],
        )

    if template == "threaded_boss":
        add_candidate(
            "Add two offset through-holes in the base using the existing bore size",
            "through_offset",
            [
                "Two offset base holes using existing bore",
                "    with BuildSketch(Plane.XY.offset(base_t)):",
                "        with Locations((-(base_w * 0.28), 0), (base_w * 0.28, 0)):",
                "            Circle(bore / 2)",
                "    extrude(amount=-base_t, mode=Mode.SUBTRACT)",
            ],
        )
        add_candidate(
            "Add four base mounting holes in a 2x2 grid using the existing bore size",
            "through_grid",
            [
                "Base 2x2 mounting hole grid using existing bore",
                "    with BuildSketch(Plane.XY.offset(base_t)):",
                "        with GridLocations(base_w * 0.55, base_w * 0.55, 2, 2):",
                "            Circle(bore / 2)",
                "    extrude(amount=-base_t, mode=Mode.SUBTRACT)",
            ],
        )

    return candidates


def build_hole_edit_candidates(template_records: list[dict], rng: random.Random) -> list[dict]:
    candidates: list[dict] = []
    for record in template_records:
        candidates.extend(hole_candidates_for_record(record))
    rng.shuffle(candidates)
    return candidates


def interleave_by_key(records: list[dict], key: str, rng: random.Random) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[str(record.get(key, ""))].append(record)

    keys = sorted(groups)
    for group in groups.values():
        rng.shuffle(group)

    ordered: list[dict] = []
    while True:
        made_progress = False
        for group_key in keys:
            group = groups[group_key]
            if group:
                ordered.append(group.pop())
                made_progress = True
        if not made_progress:
            break
    return ordered


def strip_export_lines(code: str) -> str:
    kept: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("export_step(") or stripped.startswith("export_stl("):
            continue
        kept.append(line)
    return "\n".join(kept)


def validate_code_with_metrics_in_process(code: str) -> dict | None:
    namespace: dict = {}
    try:
        exec(strip_export_lines(code), namespace)
        shape = namespace.get("result")
        if shape is None and "part" in namespace:
            shape = namespace["part"].part
        if shape is None:
            return None

        bbox = shape.bounding_box()
        dims = [
            float(bbox.max.X - bbox.min.X),
            float(bbox.max.Y - bbox.min.Y),
            float(bbox.max.Z - bbox.min.Z),
        ]
        if any(dim <= 0.0 or dim > 5000.0 for dim in dims):
            return None

        volume = float(getattr(shape, "volume", 0.0))
        if volume <= 0.0:
            return None

        surface_area = float(getattr(shape, "area", 0.0))

        is_valid = True
        raw_is_valid = getattr(shape, "is_valid", None)
        if raw_is_valid is not None:
            is_valid = bool(raw_is_valid()) if callable(raw_is_valid) else bool(raw_is_valid)
        if not is_valid:
            return None

        metrics = {
            "bbox": [round(dim, 4) for dim in dims],
            "volume": round(volume, 6),
            "surface_area": round(surface_area, 6),
            "is_valid": is_valid,
            "watertight": is_valid,
            "is_manifold": is_valid,
            "face_count": len(shape.faces()) if hasattr(shape, "faces") else 0,
            "edge_count": len(shape.edges()) if hasattr(shape, "edges") else 0,
            "vertex_count": len(shape.vertices()) if hasattr(shape, "vertices") else 0,
        }
        return metrics
    except Exception:
        return None
    finally:
        namespace.clear()


def validate_code_with_metrics_subprocess(code: str, timeout: int = 60) -> dict | None:
    harness = f"""
import json

namespace = {{}}
output = {{"ok": False}}
try:
    exec({strip_export_lines(code)!r}, namespace)
    shape = namespace.get("result")
    if shape is None and "part" in namespace:
        shape = namespace["part"].part
    if shape is None:
        raise RuntimeError("no result object found")

    bbox = shape.bounding_box()
    dims = [
        float(bbox.max.X - bbox.min.X),
        float(bbox.max.Y - bbox.min.Y),
        float(bbox.max.Z - bbox.min.Z),
    ]
    volume = float(getattr(shape, "volume", 0.0))
    surface_area = float(getattr(shape, "area", 0.0))

    raw_is_valid = getattr(shape, "is_valid", None)
    if raw_is_valid is None:
        is_valid = True
    elif callable(raw_is_valid):
        is_valid = bool(raw_is_valid())
    else:
        is_valid = bool(raw_is_valid)

    output = {{
        "ok": True,
        "bbox": [round(dim, 4) for dim in dims],
        "volume": round(volume, 6),
        "surface_area": round(surface_area, 6),
        "is_valid": is_valid,
        "watertight": is_valid,
        "is_manifold": is_valid,
        "face_count": len(shape.faces()) if hasattr(shape, "faces") else 0,
        "edge_count": len(shape.edges()) if hasattr(shape, "edges") else 0,
        "vertex_count": len(shape.vertices()) if hasattr(shape, "vertices") else 0,
    }}
except Exception as exc:
    output = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}" }}

print(json.dumps(output))
"""

    try:
        proc = subprocess.run(
            [sys.executable, "-c", harness],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return None

    if not payload.get("ok"):
        return None
    if payload["volume"] <= 0.0:
        return None
    if any(dim <= 0.0 or dim > 5000.0 for dim in payload["bbox"]):
        return None
    if not payload["is_valid"]:
        return None
    payload.pop("ok", None)
    return payload


def validate_code_with_metrics(code: str) -> dict | None:
    if "fillet(" in code or "chamfer(" in code:
        return validate_code_with_metrics_subprocess(code)
    return validate_code_with_metrics_in_process(code)


def decorate_validated_record(record: dict, metrics: dict) -> dict:
    clone = deep_copy(record)
    assistant_code = next(
        (m.get("content", "") for m in clone["messages"] if m.get("role") == "assistant"),
        "",
    )
    validation = clone.setdefault("_validation", {})
    validation["passed"] = True
    validation["stage_failed"] = None
    validation["error"] = None
    validation["code_hash"] = stripped_code_hash(assistant_code)
    validation["geometry_metrics"] = deep_copy(metrics)
    validation["warnings"] = []
    clone["geometry_metrics"] = deep_copy(metrics)
    return clone


def take_valid_records(
    records: list[dict],
    target: int,
    cache: dict[str, dict | None],
    seen_hashes: set[str],
    label: str,
) -> list[dict]:
    selected: list[dict] = []
    for idx, record in enumerate(records, 1):
        assistant_code = next(
            (m.get("content", "") for m in record["messages"] if m.get("role") == "assistant"),
            "",
        )
        code_hash = stripped_code_hash(assistant_code)
        if code_hash in seen_hashes:
            continue

        if code_hash not in cache:
            cache[code_hash] = validate_code_with_metrics(assistant_code)
        metrics = cache[code_hash]
        if metrics is None:
            continue

        selected.append(decorate_validated_record(record, metrics))
        seen_hashes.add(code_hash)

        if len(selected) % 100 == 0 or len(selected) == target:
            print(f"{label}: kept {len(selected)}/{target} after scanning {idx}")
            gc.collect()

        if len(selected) == target:
            break

    if len(selected) != target:
        raise RuntimeError(f"{label}: needed {target}, found {len(selected)}")
    return selected


def take_valid_records_by_bucket(
    records: list[dict],
    key: str,
    targets: dict[str, int],
    cache: dict[str, dict | None],
    seen_hashes: set[str],
    label: str,
) -> list[dict]:
    chosen: list[dict] = []
    remaining = dict(targets)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key, ""))].append(record)

    for bucket, target in remaining.items():
        bucket_records = grouped.get(bucket, [])
        bucket_label = f"{label}:{bucket}"
        chosen.extend(take_valid_records(bucket_records, target, cache, seen_hashes, bucket_label))

    return chosen


def build_dataset() -> tuple[list[dict], Counter]:
    rng = random.Random(SEED)
    pools, stats = load_base_pools()

    cache: dict[str, dict | None] = {}
    seen_hashes: set[str] = set()

    param_candidates = interleave_by_key(pools["template_edit_param"], "base_template", rng)

    template_generation = interleave_by_key(pools["template"], "template", rng)
    hole_candidates = build_hole_edit_candidates(template_generation, rng)
    hole_candidates = interleave_by_key(hole_candidates, "base_template", rng)

    param_records = take_valid_records(
        param_candidates,
        TARGET_PARAM_EDITS,
        cache,
        seen_hashes,
        "param_edits",
    )

    hole_targets = {
        "through_center": 150,
        "through_offset": 170,
        "through_grid": 170,
        "blind_center": 105,
        "blind_offset": 105,
    }
    hole_records = take_valid_records_by_bucket(
        hole_candidates,
        "hole_edit_pattern",
        hole_targets,
        cache,
        seen_hashes,
        "hole_adds",
    )

    gen_records = take_valid_records(
        template_generation,
        TARGET_GENS,
        cache,
        seen_hashes,
        "generation",
    )

    add_records: list[dict] = []
    final_dataset = param_records + add_records + hole_records + gen_records
    rng.shuffle(final_dataset)

    stats["selected_param_edits"] = len(param_records)
    stats["selected_surface_adds"] = len(add_records)
    stats["selected_hole_adds"] = len(hole_records)
    stats["selected_generations"] = len(gen_records)
    stats["selected_total"] = len(final_dataset)

    if len(final_dataset) != TARGET_TOTAL:
        raise RuntimeError(f"expected {TARGET_TOTAL} records, found {len(final_dataset)}")

    return final_dataset, stats


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
