"""Engineering Intent Parser — the structured spec stage of Generate.

Converts a natural-language design request into an :class:`EngineeringSpec`
*before* any geometry reasoning happens. The parser never designs anything:
it extracts what the user actually said, normalizes units to mm, and records
what the user did NOT say in ``unresolved`` instead of inventing values.

Anti-hallucination is enforced deterministically, not by prompt alone: every
numeric value in the parsed spec must be traceable to a number in the user's
message (after exact unit conversion). Ungrounded values are stripped and
moved to ``unresolved``, with the removal noted for the trajectory audit.
Free-text fields (interfaces, constraints) are carried verbatim and are not
numerically enforced.

LLM-backed when a client is supplied; falls back to pure-regex extraction
when the call fails or returns garbage, so this stage can never block a
Generate turn. Deterministic, stdlib-only post-processing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #

_UNIT_MM = {
    "mm": 1.0, "millimeter": 1.0, "millimeters": 1.0,
    "millimetre": 1.0, "millimetres": 1.0,
    "cm": 10.0, "centimeter": 10.0, "centimeters": 10.0,
    "centimetre": 10.0, "centimetres": 10.0,
    "m": 1000.0, "meter": 1000.0, "meters": 1000.0,
    "metre": 1000.0, "metres": 1000.0,
    "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4,
}

# Longest alternatives first so "mm" wins over "m".
_UNIT_RE = (r"(millimetres?|millimeters?|centimetres?|centimeters?|metres?|"
            r"meters?|inch(?:es)?|mm|cm|in|m|\")")
_NUM_RE = r"(\d+(?:\.\d+)?)"

_COUNT_NOUNS = (r"(holes?|bolts?|screws?|bores?|slots?|ribs?|fins?|arms?|"
                r"spokes?|teeth|pockets?|standoffs?|posts?|pins?|tabs?|"
                r"counterbores?|mounts?)")

_ALLOY_RE = r"\b(\d{4})[- ]?t(\d{1,2})\b"
_KNOWN_ALLOYS = {"6061", "7075", "5052", "6063", "2024", "304", "316", "4140"}
_MATERIAL_WORDS = (
    "aluminum", "aluminium", "stainless steel", "steel", "titanium", "brass",
    "copper", "bronze", "nylon", "delrin", "acetal", "polycarbonate", "abs",
    "pla", "petg", "peek", "hdpe", "uhmw", "plywood", "carbon fiber",
    "carbon fibre",
)
_MANUFACTURING = (
    ("3-axis", "3-axis CNC"), ("5-axis", "5-axis CNC"), ("cnc", "CNC"),
    ("3d print", "3D printing"), ("3d-print", "3D printing"),
    ("printed", "3D printing"), ("fdm", "3D printing"), ("sla", "3D printing"),
    ("machin", "machining"), ("milled", "machining"), ("milling", "machining"),
    ("lathe", "turning"), ("turned", "turning"),
    ("sheet metal", "sheet metal"), ("laser cut", "laser cutting"),
    ("waterjet", "waterjet"), ("injection mold", "injection molding"),
    ("injection mould", "injection molding"), ("cast", "casting"),
)

_MAX_ITEMS = 32          # defensive cap on any spec collection


def _to_mm(value: float, unit: str) -> float:
    return value * _UNIT_MM.get(unit.lower().strip(), 1.0)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.02, 0.002 * max(abs(a), abs(b)))


# --------------------------------------------------------------------------- #
# deterministic extraction from the raw request
# --------------------------------------------------------------------------- #


def extract_quantities(text: str) -> dict:
    """Every number the user actually stated, for grounding.

    Returns ``{"mm": [...], "raw": [...], "counts": {noun: n}}`` where ``mm``
    holds unit-qualified values converted to millimetres and ``raw`` holds
    every numeric literal verbatim (so unitless spec values can still ground).
    """
    low = text.lower()
    mm: list[float] = []
    raw: list[float] = []

    for m in re.finditer(_NUM_RE, low):
        raw.append(float(m.group(1)))

    for m in re.finditer(_NUM_RE + r"\s*" + _UNIT_RE + r"\b", low):
        mm.append(_to_mm(float(m.group(1)), m.group(2)))

    # "16x19" / "16×19" patterns: a trailing unit qualifies both numbers.
    for m in re.finditer(_NUM_RE + r"\s*[x×]\s*" + _NUM_RE
                         + r"(?:\s*" + _UNIT_RE + r"\b)?", low):
        unit = m.group(3) or "mm"
        mm.append(_to_mm(float(m.group(1)), unit))
        mm.append(_to_mm(float(m.group(2)), unit))

    # Thread callouts (M5, M8x1.25): the nominal grounds as a diameter.
    for m in re.finditer(r"\bm(\d+(?:\.\d+)?)\b", low):
        raw.append(float(m.group(1)))

    counts: dict[str, int] = {}
    for m in re.finditer(r"(\d+)\s*(?:x\s*)?" + _COUNT_NOUNS + r"\b", low):
        counts[m.group(2)] = int(m.group(1))

    return {"mm": mm, "raw": raw, "counts": counts}


def _find_material(text: str) -> str:
    low = text.lower()
    parts: list[str] = []
    m = re.search(_ALLOY_RE, low)
    if m:
        parts.append(f"{m.group(1)}-T{m.group(2)}")
    else:
        m = re.search(r"\b(" + "|".join(_KNOWN_ALLOYS) + r")\b", low)
        if m:
            parts.append(m.group(1))
    for word in _MATERIAL_WORDS:
        if word in low:
            parts.append(word)
            break
    return " ".join(parts)


def _find_manufacturing(text: str) -> str:
    low = text.lower()
    for cue, canonical in _MANUFACTURING:
        if cue in low:
            return canonical
    return ""


_STOPWORDS = {"a", "an", "the", "with", "and", "of", "is", "at", "to", "must",
              "be", "in", "on", "for", "it", "its", "uses", "using", "has"}


def _regex_dimensions(text: str) -> dict[str, float]:
    """Fallback naming: the words immediately before 'NUMBER unit'."""
    dims: dict[str, float] = {}
    low = text.lower()
    for m in re.finditer(r"([a-z][a-z\- ]{0,30}?)[\s:=]+" + _NUM_RE
                         + r"\s*" + _UNIT_RE + r"\b", low):
        words = [w for w in m.group(1).split() if w not in _STOPWORDS]
        name = " ".join(words[-2:]) if words else f"dim_{len(dims) + 1}"
        if name not in dims:
            dims[name] = _to_mm(float(m.group(2)), m.group(3))
        if len(dims) >= _MAX_ITEMS:
            break
    return dims


# --------------------------------------------------------------------------- #
# the spec
# --------------------------------------------------------------------------- #


@dataclass
class EngineeringSpec:
    part: str = ""
    material: str = ""                # exactly as stated; empty if unstated
    manufacturing: str = ""
    dimensions: dict[str, float] = field(default_factory=dict)   # name -> mm
    counts: dict[str, int] = field(default_factory=dict)
    interfaces: list[str] = field(default_factory=list)          # verbatim
    constraints: list[str] = field(default_factory=list)         # verbatim
    unresolved: list[str] = field(default_factory=list)          # stated gaps
    # Retrieved standard dimensions (bearings/fasteners/NEMA) — the sanctioned
    # channel for numbers the user never typed; NOT grounding-guarded.
    standards: list[dict] = field(default_factory=list)
    source: str = ""                  # llm | regex
    notes: str = ""                   # grounding audit trail

    def is_empty(self) -> bool:
        return not (self.part or self.material or self.manufacturing
                    or self.dimensions or self.counts or self.interfaces
                    or self.constraints or self.unresolved or self.standards)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        """Compact block for prompt injection. Empty string if nothing to say."""
        if self.is_empty():
            return ""
        lines: list[str] = []
        if self.part:
            lines.append(f"Part: {self.part}")
        if self.material:
            lines.append(f"Material: {self.material}")
        if self.manufacturing:
            lines.append(f"Manufacturing: {self.manufacturing}")
        if self.dimensions:
            lines.append("Stated dimensions (use EXACTLY these values, in mm):")
            lines += [f"  - {k}: {v:g} mm" for k, v in self.dimensions.items()]
        if self.counts:
            lines.append("Stated counts:")
            lines += [f"  - {k}: {v}" for k, v in self.counts.items()]
        if self.interfaces:
            lines.append("Interfaces:")
            lines += [f"  - {i}" for i in self.interfaces]
        if self.constraints:
            lines.append("Constraints (verbatim):")
            lines += [f"  - {c}" for c in self.constraints]
        if self.standards:
            lines.append(
                "Standards (retrieved, authoritative — use EXACTLY these "
                "dimensions, never guessed alternatives; entries marked "
                "'candidate' are options to choose from and state your choice):")
            for s in self.standards:
                tag = " [candidate]" if s.get("candidate") else ""
                lines.append(f"  - {s.get('text', '')}{tag}")
        if self.unresolved:
            lines.append(
                "Unresolved (NOT stated by the user — choose a sensible default, "
                "state it explicitly as an assumption in your answer, and NEVER "
                "present it as a user requirement):")
            lines += [f"  - {u}" for u in self.unresolved]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# LLM extraction
# --------------------------------------------------------------------------- #

_EXTRACTION_PROMPT = (
    "You are an engineering requirements extractor for a CAD system. Read the "
    "user's design request and return ONLY a JSON object (no prose, no code "
    "fence) with exactly this shape:\n"
    "{\n"
    '  "part": "<short part name>",\n'
    '  "material": "<material exactly as stated, or empty string>",\n'
    '  "manufacturing": "<process exactly as stated, or empty string>",\n'
    '  "dimensions": {"<descriptive_name>": {"value": <number>, "unit": "mm"}},\n'
    '  "counts": {"<thing being counted>": <integer>},\n'
    '  "interfaces": [{"name": "<interface>", "detail": "<verbatim details>"}],\n'
    '  "constraints": ["<non-geometric requirement, verbatim>"],\n'
    '  "unresolved": ["<info a CAD engineer needs that the user did NOT give>"]\n'
    "}\n"
    "Hard rules:\n"
    "- Copy every number exactly as the user stated it. Convert units to mm "
    "only by exact arithmetic (1 cm = 10 mm, 1 in = 25.4 mm).\n"
    "- NEVER invent, estimate, or derive a value the user did not state. If "
    "it is missing but needed, name it in \"unresolved\".\n"
    "- Do not design anything. No geometry, no sketches, no code. Extraction only."
)


def _first_json_object(text: str) -> Optional[dict]:
    """Brace-matched extraction of the first top-level JSON object."""
    import json
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def _coerce_mm(value: Any) -> Optional[float]:
    """'140 mm' | 140 | {'value': 140, 'unit': 'mm'} -> mm float."""
    if isinstance(value, dict):
        unit = str(value.get("unit", "mm"))
        try:
            return _to_mm(float(value.get("value")), unit)
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"\s*" + _NUM_RE + r"\s*" + _UNIT_RE + r"?\s*$", value.lower())
        if m:
            return _to_mm(float(m.group(1)), m.group(2) or "mm")
    return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:_MAX_ITEMS]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            detail = str(item.get("detail", "")).strip()
            joined = ": ".join(p for p in (name, detail) if p)
            if joined:
                out.append(joined)
    return out


class SpecParser:
    """LLM-backed extraction with a deterministic grounding guard and a
    regex-only fallback. ``parse`` never raises."""

    def __init__(self, llm=None):
        self.llm = llm

    # ------------------------------------------------------------------ #
    def parse(self, message: str) -> EngineeringSpec:
        spec = None
        if self.llm is not None:
            spec = self._parse_llm(message)
        if spec is None:
            spec = self._parse_regex(message)
            spec.source = "regex"
        else:
            spec.source = "llm"
        # Deterministic backstop: material/manufacturing the LLM missed.
        if not spec.material:
            spec.material = _find_material(message)
        if not spec.manufacturing:
            spec.manufacturing = _find_manufacturing(message)
        self._ground(spec, message)
        # Standards named in the request resolve to real dimensions here —
        # retrieved knowledge, never the LLM's recollection.
        from orion_agent.harness import standards
        spec.standards = standards.detect(message)
        return spec

    # ------------------------------------------------------------------ #
    def _parse_llm(self, message: str) -> Optional[EngineeringSpec]:
        from orion_agent.harness.llm.base import LLMMessage
        try:
            resp = self.llm.chat([
                LLMMessage.system(_EXTRACTION_PROMPT),
                LLMMessage.user(message),
            ])
        except Exception:  # noqa: BLE001
            return None
        if resp is None or resp.finish_reason == "error":
            return None
        data = _first_json_object(resp.content or "")
        if data is None:
            return None

        spec = EngineeringSpec(
            part=str(data.get("part", "") or "").strip(),
            material=str(data.get("material", "") or "").strip(),
            manufacturing=str(data.get("manufacturing", "") or "").strip(),
            interfaces=_str_list(data.get("interfaces")),
            constraints=_str_list(data.get("constraints")),
            unresolved=_str_list(data.get("unresolved")),
        )
        dims = data.get("dimensions")
        if isinstance(dims, dict):
            for name, value in list(dims.items())[:_MAX_ITEMS]:
                mm = _coerce_mm(value)
                if mm is not None:
                    spec.dimensions[str(name)] = mm
                else:
                    spec.unresolved.append(str(name))
        counts = data.get("counts")
        if isinstance(counts, dict):
            for name, value in list(counts.items())[:_MAX_ITEMS]:
                try:
                    spec.counts[str(name)] = int(value)
                except (TypeError, ValueError):
                    continue
        return spec

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_regex(message: str) -> EngineeringSpec:
        q = extract_quantities(message)
        return EngineeringSpec(
            material=_find_material(message),
            manufacturing=_find_manufacturing(message),
            dimensions=_regex_dimensions(message),
            counts=dict(list(q["counts"].items())[:_MAX_ITEMS]),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _ground(spec: EngineeringSpec, message: str) -> None:
        """Strip any numeric value the user never stated (the hard
        anti-hallucination guard); the name moves to ``unresolved``."""
        q = extract_quantities(message)
        stated = q["mm"] + q["raw"]
        dropped: list[str] = []

        for name in list(spec.dimensions):
            value = spec.dimensions[name]
            if not any(_close(value, s) for s in stated):
                del spec.dimensions[name]
                spec.unresolved.append(f"{name} (no value stated by the user)")
                dropped.append(f"{name}={value:g}mm")

        raw_ints = {int(r) for r in q["raw"] if float(r).is_integer()}
        for name in list(spec.counts):
            if spec.counts[name] not in raw_ints:
                value = spec.counts.pop(name)
                spec.unresolved.append(f"{name} count (not stated by the user)")
                dropped.append(f"{name}={value}")

        # Dedupe unresolved, preserving order.
        seen: set[str] = set()
        spec.unresolved = [u for u in spec.unresolved
                           if not (u in seen or seen.add(u))][:_MAX_ITEMS]
        if dropped:
            spec.notes = "grounding removed ungrounded values: " + ", ".join(dropped)
