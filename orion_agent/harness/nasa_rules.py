"""Retrieval over NASA normative requirements — traceable, never recalled.

The data in :mod:`orion_agent.knowledge.mechanical` (``nasa_rules.json``) is
transcribed verbatim from public-domain NASA Technical Standards by
``scripts/build_nasa_rule_graph.py``. Each rule keeps its standard, revision,
requirement tag, section, and page so any statement the agent surfaces can be
checked against the source document.

This module is the stable, stdlib-only read side: it loads the committed JSON
and ranks it lexically. It deliberately does no paraphrasing — a requirement is
quoted or it is not returned.

Scope caveat that callers must preserve: these are requirements on *NASA
spaceflight hardware*. They are excellent engineering defaults and terrible
compliance claims for anything else, so :func:`render` always says so.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1] / "knowledge" / "mechanical"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_REQUIRED_FIELDS = {
    "id", "standard", "revision", "requirement_tag", "domain", "page",
    "statement", "authority", "source", "topics",
}
# Query words that carry no retrieval signal here: every rule is a NASA
# requirement, so matching on these would rank the whole corpus equally.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "is", "are",
    "what", "which", "how", "do", "does", "i", "my", "with", "be", "should",
    "nasa", "standard", "requirement", "requirements", "rule", "rules",
})
_ALIASES = {
    "bolt": "fastener", "bolts": "fastener", "screw": "fastener",
    "screws": "fastener", "fasteners": "fastener", "threaded": "thread",
    "threads": "thread", "torque": "preload", "safety": "margin",
    "fos": "margin", "welding": "weld", "welds": "weld", "welded": "weld",
    "crack": "fracture", "cracks": "fracture", "flaw": "fracture",
    "gear": "mechanism", "gears": "mechanism", "bearing": "mechanism",
    "bearings": "mechanism", "actuator": "mechanism", "hinge": "mechanism",
    "materials": "material", "alloys": "material", "alloy": "material",
    "tolerances": "tolerance", "clearances": "clearance", "fit": "clearance",
    "loads": "load", "stress": "load", "fatigue": "fatigue",
}


def _read(name: str) -> dict[str, Any]:
    with (_ROOT / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def rules() -> tuple[dict[str, Any], ...]:
    """Every transcribed NASA requirement, ordered by standard and number."""
    return tuple(dict(rule) for rule in _read("nasa_rules.json")["rules"])


@lru_cache(maxsize=1)
def _sources() -> dict[str, dict[str, Any]]:
    return {record["id"]: dict(record)
            for record in _read("sources.json")["sources"]}


@lru_cache(maxsize=1)
def standards() -> tuple[str, ...]:
    return tuple(sorted({rule["standard"] for rule in rules()}))


def validate_package() -> list[str]:
    """Integrity check used by the tests and ``--check``; no JSON-schema dep."""
    errors: list[str] = []
    source_ids = set(_sources())
    seen: set[str] = set()
    for rule in rules():
        rule_id = rule.get("id", "<missing id>")
        missing = _REQUIRED_FIELDS - set(rule)
        if missing:
            errors.append(f"{rule_id}: missing {', '.join(sorted(missing))}")
        if rule_id in seen:
            errors.append(f"duplicate rule id: {rule_id}")
        seen.add(rule_id)
        if rule.get("source") not in source_ids:
            errors.append(f"{rule_id}: unknown source {rule.get('source')}")
        statement = rule.get("statement", "")
        if "shall" not in statement:
            errors.append(f"{rule_id}: statement is not normative")
        if not isinstance(rule.get("page"), int) or rule["page"] < 1:
            errors.append(f"{rule_id}: bad page {rule.get('page')!r}")
    return errors


def _tokens(text: str) -> set[str]:
    raw = set(_TOKEN_RE.findall(text.lower())) - _STOPWORDS
    return raw | {_ALIASES[token] for token in raw if token in _ALIASES}


def _searchable(rule: dict[str, Any]) -> str:
    return " ".join(filter(None, [
        rule["statement"], rule.get("section_title") or "",
        rule["domain"], " ".join(rule.get("topics", [])),
        rule["standard"], rule["requirement_tag"],
    ]))


def get(rule_id: str) -> Optional[dict[str, Any]]:
    """Fetch one requirement by stable id, e.g. ``nasa_std_5020.tfsr_3``."""
    for rule in rules():
        if rule["id"] == rule_id:
            return dict(rule)
    return None


def by_tag(tag: str) -> Optional[dict[str, Any]]:
    """Fetch by requirement tag as written in the standard, e.g. ``TFSR 3``."""
    wanted = re.sub(r"[\s\[\]]+", " ", tag).strip().upper()
    for rule in rules():
        if rule["requirement_tag"].upper() == wanted:
            return dict(rule)
    return None


def search(query: str, domain: str = "", standard: str = "",
           numeric_only: bool = False, limit: int = 5) -> list[dict[str, Any]]:
    """Rank requirements lexically, keeping provenance on every hit."""
    # An exact tag reference ("TFSR 3") is a lookup, not a search.
    tag_match = re.fullmatch(r"\s*\[?([A-Za-z]{2,6})\s*(\d+)\]?\s*", query or "")
    if tag_match:
        hit = by_tag(f"{tag_match.group(1)} {tag_match.group(2)}")
        if hit:
            return [_enrich(hit)]

    tokens = _tokens(query or "")
    if not tokens:
        return []
    domain = domain.strip().lower()
    standard = standard.strip().upper()

    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for rule in rules():
        if domain and rule["domain"] != domain:
            continue
        if standard and rule["standard"].upper() != standard:
            continue
        if numeric_only and not rule.get("has_numeric"):
            continue
        score = len(tokens & _tokens(_searchable(rule)))
        if not score:
            continue
        # A topic hit is a stronger signal than an incidental word in a long
        # statement; numeric requirements are what the compiler can act on.
        score += 2 * len(tokens & set(rule.get("topics", [])))
        if rule.get("has_numeric"):
            score += 1
        ranked.append((-score, rule["id"], rule))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [_enrich(rule) for _, _, rule in ranked[:limit]]


def _enrich(rule: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(rule)
    record = _sources().get(rule["source"])
    if record:
        enriched["source_record"] = dict(record)
    enriched["citation"] = citation(rule)
    return enriched


def citation(rule: dict[str, Any]) -> str:
    """Human-checkable pointer back into the source PDF."""
    revision = rule.get("revision") or ""
    section = f", section {rule['section']}" if rule.get("section") else ""
    return (f"{rule['standard']}{revision} [{rule['requirement_tag']}]"
            f"{section}, p.{rule['page']}")


def render(results: list[dict[str, Any]]) -> str:
    """Render requirements for the model, with the scope limit attached."""
    if not results:
        return ""
    lines: list[str] = []
    for rule in results:
        lines.append(f"- {citation(rule)}")
        if rule.get("section_title"):
            lines.append(f"  Topic: {rule['section_title']}")
        lines.append(f"  Requirement: {rule['statement']}")
        if rule.get("rationale"):
            lines.append(f"  Rationale: {rule['rationale']}")
    lines.append(
        "Scope: these are normative requirements on NASA spaceflight hardware, "
        "quoted verbatim. Use them as engineering defaults and cite the tag; do "
        "not state that a user's part is compliant.")
    return "\n".join(lines)
