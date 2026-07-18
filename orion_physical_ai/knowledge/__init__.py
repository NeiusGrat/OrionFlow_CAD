"""Mechanical-engineering knowledge base: materials, standards, heuristics,
DFM rules, and a robotics standard-parts catalog.

The knowledge lives in JSON (data, not code) so it can be versioned, extended,
and injected into LLM prompts. The LLM queries it — it never invents a
clearance diameter or a NEMA bolt circle.
"""

import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).parent


def _load(name: str) -> dict:
    with open(_ROOT / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


class KnowledgeBase:
    """Typed access to the engineering knowledge JSONs."""

    def __init__(self):
        self.materials = _load("materials")
        self.standards = _load("standards")
        self.heuristics = _load("heuristics")
        self.dfm_rules = _load("dfm_rules")
        self.parts = _load("parts_db")

    # ── lookups ──────────────────────────────────────────────────

    def material(self, name: str) -> dict:
        key = name.strip().lower().replace("-", "_").replace(" ", "_")
        if key not in self.materials:
            raise KeyError(
                f"Unknown material {name!r}. Available: {sorted(self.materials)}"
            )
        return self.materials[key]

    def clearance_hole(self, thread: str, fit: str = "normal") -> float:
        table = (
            self.standards["metric_bolt_clearance_close_mm"]
            if fit == "close"
            else self.standards["metric_bolt_clearance_mm"]
        )
        key = thread.upper().replace(" ", "")
        if key not in table:
            raise KeyError(f"No clearance entry for {thread!r}. Available: {sorted(table)}")
        return table[key]

    def tap_drill(self, thread: str) -> float:
        table = self.standards["metric_tap_drill_mm"]
        key = thread.upper().replace(" ", "")
        if key not in table:
            raise KeyError(f"No tap-drill entry for {thread!r}. Available: {sorted(table)}")
        return table[key]

    def nema(self, size: str) -> dict:
        key = size.upper().replace(" ", "")
        return self.standards["nema_motors"][key]

    def part(self, part_id: str) -> dict:
        if part_id not in self.parts:
            raise KeyError(f"Unknown part {part_id!r}")
        return self.parts[part_id]

    def dfm(self, process: str) -> dict:
        return self.dfm_rules[process]

    def nearest_standard_drill(self, diameter_mm: float) -> float:
        sizes = self.standards["standard_drill_sizes_mm"]
        return min(sizes, key=lambda s: abs(s - diameter_mm))

    # ── prompt grounding ─────────────────────────────────────────

    def constraints_for_parts(self, part_ids: list[str]) -> list[str]:
        """Hard dimensional facts for the given parts, as prompt-ready lines."""
        lines: list[str] = []
        for pid in part_ids:
            p = self.parts.get(pid)
            if not p:
                continue
            facts = [
                f"{k}={v}"
                for k, v in p.items()
                if k not in ("name", "category") and not isinstance(v, dict)
            ]
            lines.append(f"{p['name']}: " + ", ".join(facts))
        return lines


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase()
