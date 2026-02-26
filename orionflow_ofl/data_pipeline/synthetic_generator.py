"""Template-based synthetic OFL training pair generator."""

from __future__ import annotations

import random
from typing import Any

from .templates.part_templates import ALL_TEMPLATES, PartTemplate


class SyntheticGenerator:
    """Generate (text, code) training pairs from parametric templates."""

    def __init__(self, seed: int | None = None):
        self._templates = {T.name: T for T in ALL_TEMPLATES}
        if seed is not None:
            random.seed(seed)

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())

    def generate_one(self) -> tuple[str, str]:
        """Generate a single random (text, code) pair."""
        cls = random.choice(ALL_TEMPLATES)
        return cls().generate()

    def generate_from_template(self, name: str) -> tuple[str, str]:
        """Generate a pair from a specific template by name."""
        cls = self._templates[name]
        return cls().generate()

    def generate_batch(self, num_samples: int) -> list[dict]:
        """Generate *num_samples* training pairs with metadata."""
        pairs: list[dict] = []
        for _ in range(num_samples):
            cls = random.choice(ALL_TEMPLATES)
            inst = cls()
            text, code = inst.generate()
            pairs.append({
                "text": text,
                "code": code,
                "source": "synthetic",
                "complexity": inst.complexity,
                "template": inst.name,
            })
        return pairs
