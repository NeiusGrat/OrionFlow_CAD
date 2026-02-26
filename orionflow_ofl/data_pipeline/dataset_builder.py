"""Orchestrator: build final training JSONL from all sources."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

from .deepcad_converter import DeepCADConverter
from .synthetic_generator import SyntheticGenerator
from .text_annotator import TextAnnotator
from .validator import OFLValidator


class DatasetBuilder:
    """Builds the final training_pairs.jsonl from all sources."""

    def __init__(self, output_dir: str = "data/training"):
        self.converter = DeepCADConverter()
        self.generator = SyntheticGenerator()
        self.annotator = TextAnnotator()
        self.validator = OFLValidator()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # DeepCAD source
    # ------------------------------------------------------------------
    def build_from_deepcad(
        self,
        deepcad_dir: str,
        text_annotations: dict | None = None,
        max_models: int = 0,
    ) -> str:
        """Convert DeepCAD models -> OFL, pair with text, save JSONL."""
        json_files = sorted(Path(deepcad_dir).glob("*.json"))
        if max_models > 0:
            json_files = json_files[:max_models]

        pairs: list[dict] = []
        converted = 0
        skipped = 0

        for jf in json_files:
            model_id = jf.stem
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                skipped += 1
                continue
            code = self.converter.convert(data, model_id=model_id)
            if code is None:
                skipped += 1
                continue
            converted += 1

            # generate text descriptions
            if text_annotations and model_id in text_annotations:
                texts = [text_annotations[model_id]]
            else:
                texts = self.annotator.annotate_from_code(code)

            for text in texts:
                pairs.append({
                    "text": text,
                    "code": code,
                    "source": "deepcad",
                    "complexity": self._estimate_complexity(code),
                })

        out_path = os.path.join(self.output_dir, "deepcad_pairs.jsonl")
        self._write_jsonl(pairs, out_path)

        report = {
            "total_files": len(json_files),
            "converted": converted,
            "skipped": skipped,
            "pairs_generated": len(pairs),
        }
        report_path = os.path.join(self.output_dir, "conversion_report.json")
        Path(report_path).write_text(json.dumps(report, indent=2))
        print(f"DeepCAD: {converted} converted, {skipped} skipped, {len(pairs)} pairs")
        return out_path

    # ------------------------------------------------------------------
    # Synthetic source
    # ------------------------------------------------------------------
    def build_synthetic(self, num_samples: int = 5000) -> str:
        """Generate synthetic training pairs, save JSONL."""
        pairs = self.generator.generate_batch(num_samples)
        out_path = os.path.join(self.output_dir, "synthetic_pairs.jsonl")
        self._write_jsonl(pairs, out_path)

        report = {
            "total_generated": len(pairs),
            "template_counts": {},
        }
        for p in pairs:
            t = p.get("template", "unknown")
            report["template_counts"][t] = report["template_counts"].get(t, 0) + 1
        report_path = os.path.join(self.output_dir, "generation_report.json")
        Path(report_path).write_text(json.dumps(report, indent=2))
        print(f"Synthetic: {len(pairs)} pairs generated")
        return out_path

    # ------------------------------------------------------------------
    # Examples source
    # ------------------------------------------------------------------
    def build_from_examples(self, examples_dir: str = "orionflow_ofl/examples/") -> str:
        """Convert hand-written examples into training pairs (5 texts each)."""
        examples_path = Path(examples_dir)
        py_files = sorted(examples_path.glob("*.py"))
        pairs: list[dict] = []

        for pf in py_files:
            code_raw = pf.read_text(encoding="utf-8")
            # strip sys.path and print lines for training data
            code = self._clean_example_code(code_raw)
            if "export(" not in code:
                continue
            texts = self.annotator.annotate_from_code(code)
            for text in texts:
                pairs.append({
                    "text": text,
                    "code": code,
                    "source": "example",
                    "complexity": self._estimate_complexity(code),
                })

        out_path = os.path.join(self.output_dir, "example_pairs.jsonl")
        self._write_jsonl(pairs, out_path)
        print(f"Examples: {len(py_files)} scripts -> {len(pairs)} pairs")
        return out_path

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    def merge_and_deduplicate(self, jsonl_files: list[str], output: str) -> dict:
        """Merge multiple JSONL files, deduplicate by code hash, shuffle."""
        seen_hashes: set[str] = set()
        all_pairs: list[dict] = []

        for fpath in jsonl_files:
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    pair = json.loads(line)
                    h = hashlib.md5((pair["text"] + pair["code"]).encode()).hexdigest()
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        all_pairs.append(pair)

        random.shuffle(all_pairs)
        self._write_jsonl(all_pairs, output)

        source_counts: dict[str, int] = {}
        for p in all_pairs:
            s = p.get("source", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1

        stats = {
            "total_pairs": len(all_pairs),
            "deduplicated": True,
            "source_breakdown": source_counts,
        }
        stats_path = output.replace(".jsonl", "_stats.json")
        Path(stats_path).write_text(json.dumps(stats, indent=2))
        print(f"Merged: {len(all_pairs)} unique pairs")
        return stats

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _write_jsonl(self, pairs: list[dict], path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    def _clean_example_code(self, code: str) -> str:
        """Remove sys.path hacks, docstrings, and print statements."""
        lines = []
        in_docstring = False
        for line in code.splitlines():
            stripped = line.strip()
            # skip sys.path, import sys, pathlib import
            if stripped.startswith("sys.path"):
                continue
            if stripped == "import sys":
                continue
            if stripped.startswith("from pathlib"):
                continue
            if stripped.startswith("print("):
                continue
            # skip docstrings
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if in_docstring:
                    in_docstring = False
                    continue
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = True
                    continue
                # single-line docstring
                continue
            if in_docstring:
                continue
            lines.append(line)

        # strip leading blank lines
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines)

    def _estimate_complexity(self, code: str) -> int:
        score = 1
        if "Hole(" in code:
            score += 1
        if ".at_circular(" in code:
            score += 1
        hole_count = code.count("part -=")
        if hole_count >= 2:
            score += 1
        if hole_count >= 3:
            score += 1
        return min(score, 5)
