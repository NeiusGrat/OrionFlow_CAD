"""Mass generation of diverse, validated OFL training pairs.

Scales from 100 pairs to 10K+ by:
1. Stratified dimension sampling across all 20 templates
2. Multiple text descriptions per generated part
3. Description augmentation for linguistic variety
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from .description_augmenter import DescriptionAugmenter
from .quality_filter import QualityFilter
from .synthetic_generator import SyntheticGenerator
from .templates.part_templates import ALL_TEMPLATES
from .validator import OFLValidator


class ScaleSyntheticGenerator:
    """Generate 10K+ diverse, validated training pairs."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        self.augmenter = DescriptionAugmenter()
        self.qfilter = QualityFilter()

    def generate_batch(
        self,
        num_pairs: int = 10000,
        validate: bool = True,
        validate_sample_rate: float = 0.1,
        output_path: str = "data/training/synthetic_10k.jsonl",
        workers: int = 4,
    ) -> dict:
        """Generate *num_pairs* training pairs with variety.

        Strategy:
        - For each template, produce enough code variants to hit quota
        - For each code variant, produce 2-4 text descriptions
        - Validate a random 10% sample to catch systematic errors
        - Quality-filter and balance by complexity
        """
        n_templates = len(ALL_TEMPLATES)
        codes_per_template = max(1, (num_pairs // n_templates) // 3 + 1)

        raw_pairs: list[dict] = []

        for TemplateClass in ALL_TEMPLATES:
            inst = TemplateClass()
            for _ in range(codes_per_template):
                params = inst.randomize_params()
                code = inst.generate_code(params)
                # canonical description from template
                canonical_text = inst.generate_description(params)

                # determine part type for augmenter
                part_type = self._part_type(inst.name)

                # augmented descriptions (2-4 extra)
                aug_count = random.randint(2, 4)
                aug_texts = self.augmenter.augment(params, part_type, num_variants=aug_count)

                # combine canonical + augmented (deduplicated)
                all_texts = [canonical_text]
                for t in aug_texts:
                    if t.lower().strip() != canonical_text.lower().strip():
                        all_texts.append(t)

                for text in all_texts:
                    raw_pairs.append({
                        "text": text,
                        "code": code,
                        "source": "synthetic",
                        "complexity": inst.complexity,
                        "template": inst.name,
                    })

        # shuffle
        random.shuffle(raw_pairs)

        # quality filter
        filtered = self.qfilter.filter(raw_pairs)
        filter_stats = self.qfilter.last_stats

        # balance by complexity
        balanced = self.qfilter.balance_complexity(filtered)

        # cap to requested num_pairs
        if len(balanced) > num_pairs:
            balanced = balanced[:num_pairs]

        # validate a sample (cap at 50 to keep runtime reasonable)
        validation_stats: dict = {}
        if validate and balanced:
            validator = OFLValidator()
            sample_size = min(50, max(1, int(len(balanced) * validate_sample_rate)))
            sample_indices = random.sample(range(len(balanced)), sample_size)
            valid_count = 0
            invalid_templates: dict[str, int] = {}
            for idx in sample_indices:
                res = validator.validate(balanced[idx]["code"])
                if res["valid"]:
                    valid_count += 1
                else:
                    tname = balanced[idx].get("template", "unknown")
                    invalid_templates[tname] = invalid_templates.get(tname, 0) + 1
            validation_stats = {
                "sample_size": sample_size,
                "valid": valid_count,
                "invalid": sample_size - valid_count,
                "valid_pct": round(valid_count / sample_size * 100, 1),
                "invalid_templates": invalid_templates,
            }
            if validation_stats["valid_pct"] < 95:
                print(f"WARNING: validation rate {validation_stats['valid_pct']}% < 95%")
                if invalid_templates:
                    print(f"  failing templates: {invalid_templates}")

        # save
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for p in balanced:
                out = {k: v for k, v in p.items() if k != "template"}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

        # complexity distribution
        complexity_dist: dict[int, int] = {}
        for p in balanced:
            c = p.get("complexity", 1)
            complexity_dist[c] = complexity_dist.get(c, 0) + 1

        # template distribution
        template_dist: dict[str, int] = {}
        for p in balanced:
            t = p.get("template", "unknown")
            template_dist[t] = template_dist.get(t, 0) + 1

        stats = {
            "raw_generated": len(raw_pairs),
            "after_filter": len(filtered),
            "after_balance": len(balanced),
            "final_count": len(balanced),
            "filter_stats": filter_stats,
            "validation": validation_stats,
            "complexity_distribution": dict(sorted(complexity_dist.items())),
            "template_distribution": dict(sorted(template_dist.items())),
            "output_path": output_path,
        }

        # save report
        report_path = output_path.replace(".jsonl", "_report.json")
        Path(report_path).write_text(json.dumps(stats, indent=2))

        return stats

    @staticmethod
    def _part_type(template_name: str) -> str:
        """Map template name to augmenter part_type."""
        circle_types = {
            "circular_disc", "circular_flange", "washer", "spacer",
            "bushing", "end_cap", "bearing_housing_cap", "gearbox_cover",
            "pipe_flange",
        }
        if template_name in circle_types:
            return "circle"
        return "rect"
