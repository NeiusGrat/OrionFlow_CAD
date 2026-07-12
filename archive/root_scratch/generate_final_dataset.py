"""Build the final OrionFlow training dataset from templates, examples, and edits.

This script follows the requested four-stage pipeline:
1. Generate synthetic pairs from OFL templates.
2. Convert hand-written examples into ShareGPT pairs.
3. Create validated editing pairs from the synthetic data.
4. Merge, deduplicate, filter, and write the final dataset.

The implementation is compatibility-first. It supports template modules that:
- expose variants via ``supported_variants()``, or
- only expose a single default variant, and
- expose either ``generate_descriptions()`` or only ``generate_description()``.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from orionflow_ofl.data_pipeline.templates.part_templates import ALL_TEMPLATES
from orionflow_ofl.data_pipeline.text_annotator import TextAnnotator
from orionflow_ofl.data_pipeline.validator import OFLValidator


SYSTEM_PROMPT_GENERATE = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part description, "
    "generate valid OFL Python code that compiles to a 3D STEP model. Use descriptive "
    "variable names and add comments for each feature. Always include from "
    "orionflow_ofl import * and export(part, 'model.step')."
)

SYSTEM_PROMPT_EDIT = (
    "You are OrionFlow, an AI mechanical design copilot. The user will show you "
    "existing OFL code and request a modification. Output the complete modified OFL "
    "code preserving all existing features."
)

TRAINING_DIR = Path("data/training")
SYNTHETIC_PATH = TRAINING_DIR / "synthetic_from_templates.jsonl"
EXAMPLES_PATH = TRAINING_DIR / "example_pairs.jsonl"
EDITING_PATH = TRAINING_DIR / "editing_pairs.jsonl"
FINAL_PATH = TRAINING_DIR / "ofl_final_v2.jsonl"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples-per-variant", type=int, default=100)
    parser.add_argument("--descriptions-per-code", type=int, default=3)
    parser.add_argument("--validation-sample-rate", type=float, default=0.15)
    parser.add_argument("--editing-limit", type=int, default=7000)
    parser.add_argument("--workers", type=int, default=max(1, min(os.cpu_count() or 8, 8)))
    parser.add_argument("--spot-check-count", type=int, default=20)
    return parser


def ensure_training_dir() -> None:
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def word_count(text: str) -> int:
    return len(text.split())


def feature_flags(code: str) -> dict[str, bool]:
    return {
        "holes": "Hole(" in code,
        "fillet": ".fillet(" in code,
        "chamfer": ".chamfer(" in code,
        "shell": ".shell(" in code,
        "union": "+=" in code,
        "offset": "offset=" in code,
        "bolt_circle": "at_circular" in code,
    }


def feature_names_for_code(code: str) -> list[str]:
    flags = feature_flags(code)
    return [name for name, present in flags.items() if present]


def complexity_score(code: str) -> int:
    score = 1
    if "Hole(" in code:
        score += 1
    if "+=" in code:
        score += 1
    if ".fillet(" in code or ".chamfer(" in code:
        score += 1
    if ".shell(" in code:
        score += 1
    if "offset=" in code:
        score += 1
    if "at_circular" in code:
        score += 1
    return min(score, 5)


def percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part / total * 100.0, 1)


def extract_user_message(record: dict) -> str:
    return record["messages"][1]["content"]


def extract_assistant_message(record: dict) -> str:
    return record["messages"][2]["content"]


def make_generation_record(
    description: str,
    code: str,
    source: str,
    complexity: int,
    template_name: str | None = None,
    variant: str | None = None,
) -> dict:
    record = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_GENERATE},
            {"role": "user", "content": description},
            {"role": "assistant", "content": code},
        ],
        "source": source,
        "complexity": complexity,
    }
    if template_name is not None:
        record["template_name"] = template_name
    if variant is not None:
        record["variant"] = variant
    return record


def make_edit_record(user_message: str, code: str, source: str, complexity: int) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_EDIT},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": code},
        ],
        "source": source,
        "complexity": complexity,
    }


def call_with_optional_variant(method: Any, *args: Any, variant: str | None = None) -> Any:
    signature = inspect.signature(method)
    params = list(signature.parameters.values())
    accepts_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    positional_params = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]

    if accepts_varargs:
        if variant is None:
            return method(*args)
        return method(*args, variant)

    if variant is not None and len(positional_params) >= len(args) + 1:
        return method(*args, variant)
    return method(*args)


def seeded_call(seed: int, func: Any, *args: Any, variant: str | None = None) -> Any:
    state = random.getstate()
    random.seed(seed)
    try:
        return call_with_optional_variant(func, *args, variant=variant)
    finally:
        random.setstate(state)


def template_variants(instance: Any) -> list[str]:
    if hasattr(instance, "supported_variants"):
        variants = instance.supported_variants()
        if variants:
            return [str(v) for v in variants]
    if hasattr(instance, "variants"):
        variants = getattr(instance, "variants")
        if variants:
            return [str(v) for v in variants]
    return ["default"]


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def collect_descriptions(
    instance: Any,
    params: dict,
    variant: str,
    code: str,
    target_count: int,
    base_seed: int,
    annotator: TextAnnotator,
) -> list[str]:
    descriptions: list[str] = []
    seen: set[str] = set()

    if hasattr(instance, "generate_descriptions"):
        raw = call_with_optional_variant(instance.generate_descriptions, params, variant=variant)
        if isinstance(raw, str):
            raw = [raw]
        for text in raw:
            if not isinstance(text, str):
                continue
            norm = normalize_text(text)
            if norm and norm not in seen:
                descriptions.append(text.strip())
                seen.add(norm)

    if hasattr(instance, "generate_description") and len(descriptions) < target_count:
        attempt = 0
        while len(descriptions) < target_count and attempt < 24:
            attempt_seed = base_seed + 1000 + attempt
            text = seeded_call(attempt_seed, instance.generate_description, params, variant=variant)
            if not isinstance(text, str):
                attempt += 1
                continue
            norm = normalize_text(text)
            if norm and norm not in seen and word_count(text) >= 8:
                descriptions.append(text.strip())
                seen.add(norm)
            attempt += 1

    if len(descriptions) < target_count:
        levels = annotator.annotate_from_code(code)
        for idx in (1, 2, 3, 4):
            if idx >= len(levels):
                continue
            text = levels[idx].strip()
            norm = normalize_text(text)
            if norm and norm not in seen:
                descriptions.append(text)
                seen.add(norm)
            if len(descriptions) >= target_count:
                break

    while len(descriptions) < target_count:
        fallback = (
            f"Generate OFL code for this {variant} OrionFlow part with the same dimensions "
            f"and features shown in the provided geometry description."
        )
        norm = normalize_text(fallback)
        if norm not in seen:
            descriptions.append(fallback)
            seen.add(norm)
        else:
            descriptions.append(descriptions[-1])

    return descriptions[:target_count]


def json_key(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def generate_synthetic_records(args: argparse.Namespace, annotator: TextAnnotator) -> tuple[list[dict], dict]:
    print("\nSUB-STEP A: generating synthetic template pairs")
    print(f"Detected {len(ALL_TEMPLATES)} templates in the current codebase.")

    rng = random.Random(args.seed)
    records: list[dict] = []
    code_cases: list[dict] = []
    template_counts: Counter[str] = Counter()
    complexity_counts: Counter[int] = Counter()
    feature_counts: Counter[str] = Counter()
    template_param_warnings: list[str] = []

    for template_class in ALL_TEMPLATES:
        instance = template_class()
        template_name = template_class.__name__
        variants = template_variants(instance)
        print(f"  - {template_name}: {len(variants)} variant(s)")

        for variant in variants:
            seen_params: set[str] = set()
            unique_target = args.samples_per_variant
            max_attempts = max(unique_target * 6, unique_target + 10)
            attempts = 0

            while len(seen_params) < unique_target and attempts < max_attempts:
                sample_seed = rng.randint(0, 10**9)
                attempts += 1
                try:
                    params = seeded_call(sample_seed, instance.randomize_params, variant=variant)
                except Exception as exc:
                    template_param_warnings.append(
                        f"{template_name}[{variant}] randomize_params failed: {exc}"
                    )
                    break

                key = json_key(params)
                if key in seen_params:
                    continue
                seen_params.add(key)

                try:
                    code = call_with_optional_variant(instance.generate_code, params, variant=variant)
                except Exception as exc:
                    template_param_warnings.append(
                        f"{template_name}[{variant}] generate_code failed: {exc}"
                    )
                    continue

                descriptions = collect_descriptions(
                    instance=instance,
                    params=params,
                    variant=variant,
                    code=code,
                    target_count=args.descriptions_per_code,
                    base_seed=sample_seed,
                    annotator=annotator,
                )
                score = complexity_score(code)
                code_cases.append(
                    {
                        "template_name": template_name,
                        "variant": variant,
                        "code": code,
                        "complexity": score,
                    }
                )

                for description in descriptions:
                    record = make_generation_record(
                        description=description,
                        code=code,
                        source="template",
                        template_name=template_name,
                        variant=variant,
                        complexity=score,
                    )
                    records.append(record)
                    template_counts[template_name] += 1
                    complexity_counts[score] += 1
                    for name, present in feature_flags(code).items():
                        if present:
                            feature_counts[name] += 1

            if len(seen_params) < unique_target:
                template_param_warnings.append(
                    f"{template_name}[{variant}] generated {len(seen_params)}/{unique_target} unique parameter sets"
                )

    write_jsonl(SYNTHETIC_PATH, records)
    validation = validate_template_sample(
        code_cases=code_cases,
        sample_rate=args.validation_sample_rate,
        seed=args.seed,
        workers=args.workers,
    )

    print(f"\nWrote {len(records)} synthetic records to {SYNTHETIC_PATH}")
    print("\nSynthetic summary")
    print(f"Total pairs generated: {len(records)}")
    print("Pairs per template:")
    for template_name, count in sorted(template_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {template_name}: {count}")
    print("Pairs per complexity level:")
    for level in range(1, 6):
        print(f"  Level {level}: {complexity_counts.get(level, 0)}")
    print(
        f"Validation pass rate overall: {validation['valid']}/{validation['sample_size']} "
        f"({percent(validation['valid'], validation['sample_size'])}%)"
    )
    print("Validation per template:")
    for template_name, stats in sorted(validation["per_template"].items()):
        print(
            f"  {template_name}: {stats['valid']}/{stats['total']} "
            f"({percent(stats['valid'], stats['total'])}%)"
        )
    print("Feature distribution:")
    total_records = len(records)
    for name in ("fillet", "chamfer", "shell", "holes", "union", "offset", "bolt_circle"):
        print(f"  {name}: {percent(feature_counts.get(name, 0), total_records)}%")

    if template_param_warnings:
        print("\nTemplate generation warnings:")
        for warning in template_param_warnings:
            print(f"  WARNING: {warning}")

    return records, validation


def validate_template_sample(
    code_cases: list[dict],
    sample_rate: float,
    seed: int,
    workers: int,
) -> dict:
    validator = OFLValidator()
    if not code_cases:
        return {
            "sample_size": 0,
            "valid": 0,
            "invalid": 0,
            "per_template": {},
            "warnings": [],
        }

    sample_size = max(1, int(len(code_cases) * sample_rate))
    rng = random.Random(seed + 17)
    sample = rng.sample(code_cases, min(sample_size, len(code_cases)))
    pairs = [
        {
            "code": item["code"],
            "template_name": item["template_name"],
            "variant": item["variant"],
        }
        for item in sample
    ]
    print(f"\nValidating {len(pairs)} sampled synthetic code variants...")
    results = validator.batch_validate(pairs, max_workers=workers, progress=True)

    per_template: dict[str, dict[str, int]] = defaultdict(lambda: {"valid": 0, "total": 0})
    warnings: list[dict] = []
    failing_samples: dict[str, list[dict]] = defaultdict(list)

    for item in results["valid_pairs"]:
        stats = per_template[item["template_name"]]
        stats["valid"] += 1
        stats["total"] += 1

    for item in results["invalid_pairs"]:
        stats = per_template[item["template_name"]]
        stats["total"] += 1
        failing_samples[item["template_name"]].append(item)

    for template_name, stats in sorted(per_template.items()):
        pass_rate = percent(stats["valid"], stats["total"])
        if pass_rate < 90.0:
            sample_code = ""
            sample_error = ""
            if failing_samples[template_name]:
                sample_error = failing_samples[template_name][0].get("error", "")
                sample_code = failing_samples[template_name][0]["code"]
            warnings.append(
                {
                    "template_name": template_name,
                    "pass_rate": pass_rate,
                    "error": sample_error,
                    "sample_code": sample_code,
                }
            )
            print(f"\nWARNING: {template_name} validation pass rate is {pass_rate}% (< 90%)")
            if sample_error:
                print(f"  error: {sample_error}")
            if sample_code:
                print("  failing code sample:")
                for line in sample_code.splitlines()[:16]:
                    print(f"    {line}")

    return {
        "sample_size": len(sample),
        "valid": results["valid"],
        "invalid": results["invalid"],
        "per_template": dict(per_template),
        "warnings": warnings,
        "error_summary": results["error_summary"],
    }


def clean_example_code(code: str) -> str:
    lines: list[str] = []
    in_docstring = False
    docstring_delim = ""

    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            delim = stripped[:3]
            if in_docstring and delim == docstring_delim:
                in_docstring = False
                docstring_delim = ""
                continue
            if stripped.count(delim) >= 2 and len(stripped) > 5:
                continue
            in_docstring = True
            docstring_delim = delim
            continue
        if in_docstring:
            continue
        if stripped == "import sys":
            continue
        if stripped.startswith("from pathlib import"):
            continue
        if stripped.startswith("sys.path"):
            continue
        if stripped.startswith("print("):
            continue
        lines.append(line)

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def generate_example_records(annotator: TextAnnotator) -> list[dict]:
    print("\nSUB-STEP B: converting hand-written examples")
    examples_dir = Path("orionflow_ofl/examples")
    records: list[dict] = []

    for path in sorted(examples_dir.glob("*.py")):
        raw_code = path.read_text(encoding="utf-8")
        code = clean_example_code(raw_code)
        descriptions = annotator.annotate_from_code(code)
        for idx in (1, 2, 3):
            if idx >= len(descriptions):
                continue
            description = descriptions[idx].strip()
            record = make_generation_record(
                description=description,
                code=code,
                source="handwritten",
                complexity=complexity_score(code),
            )
            record["example_name"] = path.name
            records.append(record)

    write_jsonl(EXAMPLES_PATH, records)
    print(f"Wrote {len(records)} example records to {EXAMPLES_PATH}")
    return records


def replace_numeric_assignment(code: str, var_name: str, new_value: float) -> str | None:
    pattern = re.compile(rf"(?m)^({re.escape(var_name)}\s*=\s*)(\d+\.?\d*)$")
    new_code, count = pattern.subn(rf"\g<1>{new_value}", code, count=1)
    if count != 1:
        return None
    return new_code


def insert_before_export(code: str, block: str) -> str | None:
    match = re.search(r"(?m)^export\(part,\s*.+\)$", code)
    if not match:
        return None
    start = match.start()
    return code[:start] + block + "\n" + code[start:]


def attempt_param_edit(code: str, rng: random.Random) -> tuple[str, str, str] | None:
    matches = re.findall(r"^(\w+)\s*=\s*(\d+\.?\d*)$", code, flags=re.MULTILINE)
    if not matches:
        return None

    var_name, old_raw = rng.choice(matches)
    old_value = float(old_raw)
    new_value = old_value
    for _ in range(10):
        candidate = round(old_value * rng.uniform(0.6, 1.8), 1)
        if candidate > 0 and candidate != old_value:
            new_value = candidate
            break
    if new_value == old_value:
        return None

    new_code = replace_numeric_assignment(code, var_name, new_value)
    if new_code is None:
        return None

    user_message = (
        f"Here is my current part:\n\n{code}\n\n"
        f"Modification: Change the {var_name} from {old_value:g} to {new_value:g}"
    )
    return user_message, new_code, "edit_param"


def attempt_add_hole(code: str, rng: random.Random) -> tuple[str, str, str] | None:
    if code.count("Hole(") >= 4:
        return None

    dia = rng.choice([3.4, 4.5, 5.3, 6.6, 8.5])
    block = (
        "# Added center hole\n"
        "part -= (\n"
        f"    Hole({dia})\n"
        "    .at(0, 0)\n"
        "    .through()\n"
        '    .label("added_hole")\n'
        ")\n"
    )
    new_code = insert_before_export(code, block)
    if new_code is None:
        return None

    user_message = (
        f"Here is my current part:\n\n{code}\n\n"
        f"Modification: Add a {dia:g}mm through-hole at the center of the part"
    )
    return user_message, new_code, "edit_hole"


def attempt_add_fillet(code: str, rng: random.Random) -> tuple[str, str, str] | None:
    if ".fillet(" in code:
        return None

    radius = rng.choice([0.5, 1.0, 1.5, 2.0, 3.0])
    block = f'part = part.fillet({radius}, edges="all")\n'
    new_code = insert_before_export(code, block)
    if new_code is None:
        return None

    user_message = (
        f"Here is my current part:\n\n{code}\n\n"
        f"Modification: Add {radius:g}mm fillets to all edges for deburring"
    )
    return user_message, new_code, "edit_fillet"


def build_editing_candidates(records: list[dict], seed: int) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    deduped_candidates: dict[str, dict] = {}
    stats = {
        "attempted": 0,
        "candidate_count": 0,
        "unique_candidate_count": 0,
        "skipped_not_applicable": 0,
        "strategy_attempts": Counter(),
    }

    pool = list(records)
    rng.shuffle(pool)

    for record in pool:
        code = extract_assistant_message(record)
        roll = rng.random()
        if roll < 0.4:
            strategy_name = "edit_param"
            strategy = attempt_param_edit
        elif roll < 0.7:
            strategy_name = "edit_hole"
            strategy = attempt_add_hole
        else:
            strategy_name = "edit_fillet"
            strategy = attempt_add_fillet

        stats["attempted"] += 1
        stats["strategy_attempts"][strategy_name] += 1

        result = strategy(code, rng)
        if result is None:
            stats["skipped_not_applicable"] += 1
            continue

        user_message, new_code, source = result
        candidate = {
            "code": new_code,
            "user_message": user_message,
            "source": source,
            "complexity": complexity_score(new_code),
        }
        key = hashlib.md5(new_code.encode("utf-8")).hexdigest()
        existing = deduped_candidates.get(key)
        if existing is None or len(user_message) > len(existing["user_message"]):
            deduped_candidates[key] = candidate

    candidates = list(deduped_candidates.values())
    stats["candidate_count"] = stats["attempted"] - stats["skipped_not_applicable"]
    stats["unique_candidate_count"] = len(candidates)
    return candidates, stats


def generate_editing_records(
    synthetic_records: list[dict],
    args: argparse.Namespace,
) -> tuple[list[dict], dict]:
    print("\nSUB-STEP C: generating editing pairs")
    validator = OFLValidator()
    candidates, pre_stats = build_editing_candidates(synthetic_records, seed=args.seed + 99)
    rng = random.Random(args.seed + 199)
    rng.shuffle(candidates)
    print(
        f"Built {pre_stats['unique_candidate_count']} unique editable candidates from "
        f"{pre_stats['attempted']} synthetic records"
    )

    records: list[dict] = []
    success_by_source: Counter[str] = Counter()

    invalid_by_source: Counter[str] = Counter()
    error_summary: Counter[str] = Counter()
    validated_candidates = 0
    batch_size = max(args.workers * 25, 200)

    if candidates:
        print(
            f"Validating edited candidates in batches of {batch_size} until "
            f"{args.editing_limit} valid pairs are collected..."
        )

    for start in range(0, len(candidates), batch_size):
        if len(records) >= args.editing_limit:
            break

        batch = candidates[start : start + batch_size]
        validation_pairs = [
            {
                "code": candidate["code"],
                "source": candidate["source"],
                "user_message": candidate["user_message"],
                "complexity": candidate["complexity"],
            }
            for candidate in batch
        ]
        validated_candidates += len(validation_pairs)
        print(
            f"  validating candidates {start + 1}-{start + len(validation_pairs)} "
            f"of {len(candidates)}"
        )
        results = validator.batch_validate(validation_pairs, max_workers=args.workers, progress=True)

        for item in results["valid_pairs"]:
            records.append(
                make_edit_record(
                    user_message=item["user_message"],
                    code=item["code"],
                    source=item["source"],
                    complexity=item["complexity"],
                )
            )
            success_by_source[item["source"]] += 1
            if len(records) >= args.editing_limit:
                break

        for item in results["invalid_pairs"]:
            invalid_by_source[item["source"]] += 1
        for key, value in results.get("error_summary", {}).items():
            error_summary[key] += value

    write_jsonl(EDITING_PATH, records)

    summary = {
        "attempted": pre_stats["attempted"],
        "candidate_count": pre_stats["candidate_count"],
        "unique_candidate_count": pre_stats["unique_candidate_count"],
        "skipped_not_applicable": pre_stats["skipped_not_applicable"],
        "strategy_attempts": dict(pre_stats["strategy_attempts"]),
        "validated_candidates": validated_candidates,
        "validated_success": len(records),
        "success_by_source": dict(success_by_source),
        "invalid_by_source": dict(invalid_by_source),
        "error_summary": dict(error_summary),
    }

    print(f"Wrote {len(records)} editing pairs to {EDITING_PATH}")
    print("Editing summary:")
    print(f"  Attempted records: {summary['attempted']}")
    print(f"  Candidate edits before dedup: {summary['candidate_count']}")
    print(f"  Unique candidate edits: {pre_stats['unique_candidate_count']}")
    print(f"  Candidates validated: {summary['validated_candidates']}")
    print(f"  Skipped as not applicable: {summary['skipped_not_applicable']}")
    for source in ("edit_param", "edit_hole", "edit_fillet"):
        attempted = summary["strategy_attempts"].get(source, 0)
        succeeded = summary["success_by_source"].get(source, 0)
        print(f"  {source}: {succeeded}/{attempted} valid")
    if len(records) < 5000:
        print(f"  NOTE: produced {len(records)} validated editing pairs (< 5000); moving on as requested.")

    return records, summary


def pass_final_quality_filter(record: dict) -> bool:
    user = extract_user_message(record)
    code = extract_assistant_message(record)
    if "from orionflow_ofl import *" not in code:
        return False
    if "export(" not in code:
        return False
    if code.count("\n") < 4:
        return False
    wc = word_count(user)
    if wc < 8 or wc > 200:
        return False
    return True


def merge_and_finalize(
    synthetic_records: list[dict],
    example_records: list[dict],
    editing_records: list[dict],
    spot_check_count: int,
    seed: int,
) -> list[dict]:
    print("\nSUB-STEP D: merging, deduplicating, filtering, and writing final dataset")
    combined = synthetic_records + example_records + editing_records

    deduped: dict[str, dict] = {}
    for record in combined:
        code = extract_assistant_message(record)
        key = hashlib.md5(code.encode("utf-8")).hexdigest()
        existing = deduped.get(key)
        if existing is None or len(extract_user_message(record)) > len(extract_user_message(existing)):
            deduped[key] = record

    filtered = [record for record in deduped.values() if pass_final_quality_filter(record)]
    rng = random.Random(seed)
    rng.shuffle(filtered)

    final_records = [{"messages": record["messages"]} for record in filtered]
    write_jsonl(FINAL_PATH, final_records)

    print_final_report(filtered)
    print_spot_check(filtered, count=min(spot_check_count, len(filtered)), seed=seed + 123)
    print(f"\nWrote {len(filtered)} final records to {FINAL_PATH}")
    return filtered


def print_final_report(records: list[dict]) -> None:
    total = len(records)
    source_counts = Counter(record.get("source", "unknown") for record in records)
    code_lines = [len(extract_assistant_message(record).splitlines()) for record in records]
    prompt_words = [word_count(extract_user_message(record)) for record in records]
    complexity_counts = Counter(
        record.get("complexity", complexity_score(extract_assistant_message(record)))
        for record in records
    )

    feature_dist = Counter()
    for record in records:
        code = extract_assistant_message(record)
        for name, present in feature_flags(code).items():
            if present:
                feature_dist[name] += 1

    print("\n" + "=" * 43)
    print(" OrionFlow Final Training Dataset v2")
    print("=" * 43)
    print(f" Total records:          {total}")
    print("-" * 43)
    print(f" From templates:         {source_counts.get('template', 0)}")
    print(f" From hand-written:      {source_counts.get('handwritten', 0)}")
    print(
        f" From editing pairs:     "
        f"{sum(source_counts.get(name, 0) for name in ('edit_param', 'edit_hole', 'edit_fillet'))}"
    )
    print("-" * 43)
    print(f" Avg code lines:         {mean(code_lines):.1f}" if code_lines else " Avg code lines:         0.0")
    print(f" Avg prompt words:       {mean(prompt_words):.1f}" if prompt_words else " Avg prompt words:       0.0")
    print("-" * 43)
    print(" Feature distribution:")
    print(f"   Has holes:            {percent(feature_dist.get('holes', 0), total)}%")
    print(f"   Has fillet:           {percent(feature_dist.get('fillet', 0), total)}%")
    print(f"   Has chamfer:          {percent(feature_dist.get('chamfer', 0), total)}%")
    print(f"   Has shell:            {percent(feature_dist.get('shell', 0), total)}%")
    print(f"   Has union (+=):       {percent(feature_dist.get('union', 0), total)}%")
    print(f"   Has offset plane:     {percent(feature_dist.get('offset', 0), total)}%")
    print(f"   Has bolt circle:      {percent(feature_dist.get('bolt_circle', 0), total)}%")
    print("-" * 43)
    print(" Complexity distribution:")
    print(f"   Level 1 (simple):     {percent(complexity_counts.get(1, 0), total)}%")
    print(f"   Level 2:              {percent(complexity_counts.get(2, 0), total)}%")
    print(f"   Level 3:              {percent(complexity_counts.get(3, 0), total)}%")
    print(f"   Level 4:              {percent(complexity_counts.get(4, 0), total)}%")
    print(f"   Level 5 (complex):    {percent(complexity_counts.get(5, 0), total)}%")
    print("=" * 43)


def print_spot_check(records: list[dict], count: int, seed: int) -> None:
    if not records or count <= 0:
        return

    rng = random.Random(seed)
    sample = rng.sample(records, count)
    print("\nSpot check")
    for idx, record in enumerate(sample, start=1):
        prompt = extract_user_message(record).replace("\n", " ")
        code = extract_assistant_message(record)
        features = feature_names_for_code(code)
        print(f"--- Record #{idx:02d} ---")
        print(f"PROMPT: {prompt[:150]}")
        print("CODE (first 5 lines):")
        for line in code.splitlines()[:5]:
            print(f"  {line}")
        print(f"FEATURES: {features}")
        print("---")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    ensure_training_dir()

    print("Starting OrionFlow final dataset generation")
    print(f"Seed: {args.seed}")
    print(f"Templates detected: {len(ALL_TEMPLATES)}")
    print(f"Synthetic samples per variant: {args.samples_per_variant}")
    print(f"Descriptions per code: {args.descriptions_per_code}")
    print(f"Editing limit: {args.editing_limit}")
    print(f"Validation workers: {args.workers}")

    annotator = TextAnnotator()

    synthetic_records, _ = generate_synthetic_records(args, annotator)
    example_records = generate_example_records(annotator)
    editing_records, _ = generate_editing_records(synthetic_records, args)
    merge_and_finalize(
        synthetic_records=synthetic_records,
        example_records=example_records,
        editing_records=editing_records,
        spot_check_count=args.spot_check_count,
        seed=args.seed,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
