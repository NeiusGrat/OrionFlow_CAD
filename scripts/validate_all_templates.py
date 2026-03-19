"""Validate the expanded OrionFlow template catalog.

For each registered template and supported variant, this script:
1. Generates one randomized parameter set.
2. Generates the OFL code.
3. Generates the description triplet.
4. Prints the generated code.
5. Validates the code by executing it and requiring a non-empty STEP file.
"""

from __future__ import annotations

import argparse
import inspect
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orionflow_ofl.data_pipeline.templates.part_templates import ALL_TEMPLATES
from orionflow_ofl.data_pipeline.validator import OFLValidator


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    return parser


def call_with_optional_variant(method, *args, variant: str | None = None):
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


def template_variants(instance) -> list[str]:
    if hasattr(instance, "supported_variants"):
        variants = instance.supported_variants()
        if variants:
            return list(variants)
    return ["basic"]


def main() -> int:
    args = build_arg_parser().parse_args()
    random.seed(args.seed)

    generated_cases: list[dict] = []

    for template_class in ALL_TEMPLATES:
        instance = template_class()
        for variant in template_variants(instance):
            params = call_with_optional_variant(instance.randomize_params, variant=variant)
            code = call_with_optional_variant(instance.generate_code, params, variant=variant)
            descriptions = call_with_optional_variant(instance.generate_descriptions, params, variant=variant)
            if not isinstance(descriptions, list) or len(descriptions) < 1:
                raise ValueError(f"{template_class.__name__}[{variant}] did not return descriptions")

            print("\n" + "=" * 80)
            print(f"TEMPLATE: {template_class.__name__}")
            print(f"VARIANT:  {variant}")
            print("CODE:")
            print(code)

            generated_cases.append(
                {
                    "template_name": template_class.__name__,
                    "variant": variant,
                    "code": code,
                    "description_count": len(descriptions),
                }
            )

    validator = OFLValidator()
    results = validator.batch_validate(generated_cases, max_workers=args.workers, progress=True)

    failed_lookup = {
        (item["template_name"], item["variant"]): item
        for item in results["invalid_pairs"]
    }

    print("\n" + "=" * 80)
    print("Validation Results")
    print("=" * 80)
    pass_count = 0
    fail_count = 0
    for case in generated_cases:
        key = (case["template_name"], case["variant"])
        failed = failed_lookup.get(key)
        if failed is None:
            pass_count += 1
            print(f"PASS {case['template_name']} [{case['variant']}]")
        else:
            fail_count += 1
            print(f"FAIL {case['template_name']} [{case['variant']}] :: {failed.get('error')}")

    print("\nSummary")
    print(f"  Templates registered: {len(ALL_TEMPLATES)}")
    print(f"  Template/variant cases: {len(generated_cases)}")
    print(f"  Passed: {pass_count}")
    print(f"  Failed: {fail_count}")
    print(f"  Pass rate: {round(pass_count / max(1, len(generated_cases)) * 100, 1)}%")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
