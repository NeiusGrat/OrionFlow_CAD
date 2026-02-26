"""Run baseline evaluation: Groq API + few-shot vs our eval set.

This tells us the score to BEAT with fine-tuning.

Usage:
    export GROQ_API_KEY=your_key
    python -m orionflow_ofl.baseline.baseline_eval \
        --eval-data data/eval/baseline_eval.jsonl \
        --num-samples 30 \
        --model qwen-qwq-32b
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path


def create_eval_set_from_examples(
    examples_dir: str, output: str, num: int = 30
) -> str:
    """Create eval set from hand-written examples with medium-detail prompts."""
    from orionflow_ofl.data_pipeline.text_annotator import TextAnnotator

    annotator = TextAnnotator()
    eval_pairs: list[dict] = []

    for py_file in sorted(Path(examples_dir).glob("*.py")):
        code = py_file.read_text(encoding="utf-8")
        if "from orionflow_ofl import" not in code:
            continue
        descriptions = annotator.annotate_from_code(code)
        if descriptions and len(descriptions) >= 3:
            eval_pairs.append({
                "text": descriptions[2],  # Level 3 (medium detail)
                "code": code,
                "source": py_file.stem,
            })

    random.seed(42)
    if len(eval_pairs) > num:
        eval_pairs = random.sample(eval_pairs, num)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        for pair in eval_pairs:
            f.write(json.dumps(pair) + "\n")

    print(f"Created eval set: {len(eval_pairs)} examples -> {output}")
    return output


def run_baseline(
    eval_path: str,
    model: str = "qwen-qwq-32b",
    num_samples: int = 30,
    delay: float = 2.5,
) -> dict:
    """Run baseline evaluation and return metrics."""
    from orionflow_ofl.baseline.groq_generator import GroqOFLGenerator
    from orionflow_ofl.data_pipeline.validator import OFLValidator

    generator = GroqOFLGenerator(model=model)
    validator = OFLValidator()

    examples: list[dict] = []
    with open(eval_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line))

    if num_samples < len(examples):
        examples = examples[:num_samples]

    print(f"Running baseline eval: {model}")
    print(f"Examples: {len(examples)}")
    print(f"Few-shot: 5 examples in prompt")
    print("=" * 60)

    results: list[dict] = []
    for i, ex in enumerate(examples):
        prompt = ex["text"]
        try:
            t0 = time.time()
            generated = generator.generate(prompt)
            gen_time = time.time() - t0

            validation = validator.validate(generated)
            results.append({
                "prompt": prompt[:80],
                "parseable": "from orionflow_ofl import" in generated,
                "has_export": "export(" in generated,
                "executable": validation["valid"],
                "step_size": validation.get("step_file_size", 0),
                "gen_time": round(gen_time, 2),
                "error": validation.get("error"),
            })

            status = "PASS" if validation["valid"] else "FAIL"
            print(f"  [{i + 1}/{len(examples)}] {status} ({gen_time:.1f}s) {prompt[:50]}...")

        except Exception as e:
            results.append({
                "prompt": prompt[:80],
                "parseable": False,
                "has_export": False,
                "executable": False,
                "step_size": 0,
                "gen_time": 0,
                "error": str(e),
            })
            print(f"  [{i + 1}/{len(examples)}] ERROR: {e}")

        time.sleep(delay)

    total = len(results)
    parseable = sum(1 for r in results if r["parseable"])
    has_export = sum(1 for r in results if r["has_export"])
    executable = sum(1 for r in results if r["executable"])

    report = {
        "model": model,
        "method": "few-shot (5 examples)",
        "total": total,
        "parseable_rate": round(parseable / max(total, 1) * 100, 1),
        "has_export_rate": round(has_export / max(total, 1) * 100, 1),
        "executable_rate": round(executable / max(total, 1) * 100, 1),
        "details": results,
    }

    print(f"\n{'=' * 60}")
    print(f"BASELINE RESULTS - {model}")
    print(f"{'=' * 60}")
    print(f"Total:               {total}")
    print(f"Correct imports:     {report['parseable_rate']}%")
    print(f"Has export():        {report['has_export_rate']}%")
    print(f"Produces valid STEP: {report['executable_rate']}%")
    print(f"{'=' * 60}")
    print(f"\nThis is your BASELINE. Fine-tuning must beat {report['executable_rate']}%.")

    report_path = eval_path.replace(".jsonl", "_baseline_report.json")
    Path(report_path).write_text(json.dumps(report, indent=2))
    print(f"Report saved: {report_path}")

    return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run OFL baseline eval with Groq API")
    parser.add_argument("--eval-data", default="")
    parser.add_argument("--examples-dir", default="orionflow_ofl/examples/")
    parser.add_argument("--num-samples", type=int, default=30)
    parser.add_argument("--model", default="qwen-qwq-32b")
    args = parser.parse_args()

    eval_path = args.eval_data
    if not eval_path:
        eval_path = "data/eval/baseline_eval.jsonl"
        create_eval_set_from_examples(args.examples_dir, eval_path, args.num_samples)

    run_baseline(eval_path, model=args.model, num_samples=args.num_samples)


if __name__ == "__main__":
    main()
