"""source_parts — detect standard robotics parts mentioned in a design brief
and return their exact catalog specs.

Deterministic (regex over the prompt + catalog lookup): the LLM never gets to
invent a bolt circle or a bearing OD.
"""

from __future__ import annotations

import re

from .knowledge import KnowledgeBase, get_knowledge_base

# (compiled pattern, part_id or callable(match) -> part_id)
_PATTERNS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\bnema[\s-]?17\b", re.I), "nema17_stepper"),
    (re.compile(r"\bnema[\s-]?23\b", re.I), "nema23_stepper"),
    (re.compile(r"\bnema[\s-]?14\b", re.I), "nema14_stepper"),
    (re.compile(r"\b608(?:zz|[\s-]?2rs)?\b.{0,20}?bearing|\bbearing.{0,20}?\b608\b", re.I), "608zz_bearing"),
    (re.compile(r"\b625(?:zz)?\s*bearing\b", re.I), "625zz_bearing"),
    (re.compile(r"\b688(?:zz)?\s*bearing\b", re.I), "688zz_bearing"),
    (re.compile(r"\b6001(?:zz)?\s*bearing\b", re.I), "6001zz_bearing"),
    (re.compile(r"\blm8uu\b", re.I), "lm8uu_linear_bearing"),
    (re.compile(r"\b2020\s*(?:aluminum|aluminium|alu)?\s*(?:extrusion|profile)\b", re.I), "extrusion_2020"),
    (re.compile(r"\b2040\s*(?:aluminum|aluminium|alu)?\s*(?:extrusion|profile)\b", re.I), "extrusion_2040"),
    (re.compile(r"\b3030\s*(?:aluminum|aluminium|alu)?\s*(?:extrusion|profile)\b", re.I), "extrusion_3030"),
    (re.compile(r"\bgt2\b.{0,20}?pulley|pulley.{0,20}?\bgt2\b", re.I), "gt2_pulley_20t"),
    (re.compile(r"\bgt2\b.{0,20}?belt|timing\s*belt", re.I), "gt2_belt_6mm"),
    (re.compile(r"\bsg[\s-]?90\b", re.I), "sg90_servo"),
    (re.compile(r"\bmg[\s-]?996r?\b", re.I), "mg996r_servo"),
    (re.compile(r"\braspberry\s*pi\b|\brpi\b", re.I), "raspberry_pi_4b"),
    (re.compile(r"\barduino\b", re.I), "arduino_uno"),
    (re.compile(r"\b18650\b", re.I), "battery_18650"),
    (re.compile(r"\bn20\b.{0,20}?(?:motor|gearmotor)|gearmotor.{0,20}?\bn20\b", re.I), "n20_gearmotor"),
    (re.compile(r"\b775\s*(?:dc\s*)?motor\b", re.I), "motor_775"),
    (re.compile(r"\b8\s*mm\s*(?:smooth\s*)?rod\b|linear\s*rail", re.I), "smooth_rod_8mm"),
]

# Metric fasteners: "M3", "4x M3", "M3 screws/holes/threads/mounting"
_FASTENER_RE = re.compile(r"\bM(2\.5|2|3|4|5|6|8)\b", re.I)
_FASTENER_IDS = {
    "2": "m2_shcs", "2.5": "m2_5_shcs", "3": "m3_shcs",
    "4": "m4_shcs", "5": "m5_shcs", "6": "m6_shcs",
}


def source_parts(text: str, kb: KnowledgeBase | None = None) -> list[dict]:
    """Return catalog entries for every standard part the brief mentions.

    Each hit: {"part_id", "name", "matched_text", "spec"}.
    """
    kb = kb or get_knowledge_base()
    hits: list[dict] = []
    seen: set[str] = set()

    def add(part_id: str, matched: str):
        if part_id in seen or part_id not in kb.parts:
            return
        seen.add(part_id)
        spec = kb.parts[part_id]
        hits.append(
            {
                "part_id": part_id,
                "name": spec["name"],
                "matched_text": matched,
                "spec": spec,
            }
        )

    for pattern, target in _PATTERNS:
        m = pattern.search(text)
        if m:
            add(target if isinstance(target, str) else target(m), m.group(0))

    for m in _FASTENER_RE.finditer(text):
        size = m.group(1)
        pid = _FASTENER_IDS.get(size)
        if pid:
            add(pid, m.group(0))

    return hits
