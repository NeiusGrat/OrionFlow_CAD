"""Offline tests for the NASA normative rule graph (network-free, CI-safe).

Run with:  pytest orion_agent/tests/test_nasa_rules.py -v

These assert two different things, deliberately:
  * *package integrity* — ids, sources, pages, and normativity hold for all
    705 rules, so a bad rebuild fails loudly rather than silently shipping;
  * *transcription fidelity* — a handful of requirements are pinned to their
    exact wording and citation. If ``build_nasa_rule_graph.py`` ever starts
    paraphrasing or mis-anchoring pages, these break.
"""

import re

import pytest

from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel
from orion_agent.harness import nasa_rules as nr
from orion_agent.harness.tools.registry import build_registry


def _registry():
    return build_registry(SyntheticBridge(SyntheticModel(name="X")), sandbox=None)


# --------------------------------------------------------------------------- #
# package integrity
# --------------------------------------------------------------------------- #
def test_package_validates():
    assert nr.validate_package() == []


def test_expected_standards_present():
    assert set(nr.standards()) == {
        "NASA-STD-5001", "NASA-STD-5002", "NASA-STD-5006", "NASA-STD-5009",
        "NASA-STD-5017", "NASA-STD-5019", "NASA-STD-5020", "NASA-STD-6016",
    }


def test_every_rule_is_normative_and_traceable():
    for rule in nr.rules():
        assert "shall" in rule["statement"], rule["id"]
        assert rule["page"] >= 1
        assert rule["revision"], rule["id"]
        assert re.fullmatch(r"[A-Z]{2,6} \d+", rule["requirement_tag"])


def test_no_extraction_artifacts():
    """Page furniture, private-use glyphs, and tag bleed must all be absent."""
    for rule in nr.rules():
        text = rule["statement"]
        assert not re.search(r"\[[A-Z]{2,6} ?\d+\]", text), rule["id"]
        assert "APPROVED FOR PUBLIC" not in text, rule["id"]
        assert "Controlled by" not in text, rule["id"]
        assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in text), rule["id"]


def test_rule_ids_unique_and_well_formed():
    ids = [rule["id"] for rule in nr.rules()]
    assert len(ids) == len(set(ids))
    for rule_id in ids:
        assert re.fullmatch(r"nasa_std_\d{4}\.[a-z]{2,6}_\d+", rule_id)


# --------------------------------------------------------------------------- #
# transcription fidelity — pinned against the source PDFs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tag,standard,page,fragment", [
    ("TFSR 3", "NASA-STD-5020", 18,
     "shall be designed using a fitting factor (FF)"),
    ("TFSR 7", "NASA-STD-5020", 24,
     "The preload variation, Γ, used to calculate"),
    ("FSR 24", "NASA-STD-5001", 17,
     "minimum design and test factors of safety for metallic structures"),
    ("DDMR 3", "NASA-STD-5017", 18,
     "Static and dynamic clearance requirements between mechanism components"),
    ("NER 28", "NASA-STD-5009", 21, "Film density shall be 2.5 to 4.0"),
])
def test_requirement_transcribed_verbatim(tag, standard, page, fragment):
    rule = nr.by_tag(tag)
    assert rule is not None, f"{tag} missing"
    assert rule["standard"] == standard
    assert rule["page"] == page
    assert fragment in rule["statement"]


def test_symbol_font_greek_is_repaired():
    """NASA-STD-5020 writes preload variation as capital gamma."""
    assert "Γ" in nr.by_tag("TFSR 7")["statement"]


def test_citation_format():
    rule = nr.by_tag("TFSR 3")
    assert nr.citation(rule) == "NASA-STD-5020B [TFSR 3], section 4.2.2, p.18"


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #
def test_exact_tag_query_is_a_lookup():
    hits = nr.search("TFSR 3")
    assert len(hits) == 1
    assert hits[0]["requirement_tag"] == "TFSR 3"


@pytest.mark.parametrize("query,expected_domain", [
    ("bolt preload torque", "fasteners"),
    ("weld inspection", "joining"),
    ("mechanism clearance backlash", "mechanisms"),
])
def test_search_finds_the_right_domain(query, expected_domain):
    hits = nr.search(query, limit=5)
    assert hits, query
    assert any(hit["domain"] == expected_domain for hit in hits), query


def test_filters_narrow_results():
    assert all(hit["standard"] == "NASA-STD-5020"
               for hit in nr.search("preload", standard="NASA-STD-5020"))
    assert all(hit["has_numeric"]
               for hit in nr.search("factor of safety", numeric_only=True))
    assert all(hit["domain"] == "materials"
               for hit in nr.search("corrosion", domain="materials"))


def test_search_is_empty_for_stopword_only_query():
    assert nr.search("what are the requirements") == []


def test_hits_carry_provenance():
    hit = nr.search("fitting factor")[0]
    assert hit["source_record"]["publisher"].startswith("National Aeronautics")
    assert "public domain" in hit["source_record"]["license"]
    assert hit["citation"].startswith("NASA-STD-")


def test_render_states_scope_limit():
    text = nr.render(nr.search("bolt preload", limit=2))
    assert "verbatim" in text
    assert "do not state that a user's part is compliant" in text.lower()


# --------------------------------------------------------------------------- #
# tool wiring
# --------------------------------------------------------------------------- #
def test_tool_registered_and_returns_citations():
    reg = _registry()
    result = reg.execute("lookup_nasa_requirement", {"query": "bolt preload"})
    assert result.ok
    assert "NASA-STD-" in result.content


def test_tool_fails_cleanly_on_no_match():
    reg = _registry()
    assert not reg.execute("lookup_nasa_requirement", {"query": "zzzznotathing"}).ok


def test_tool_is_available_to_the_pillars():
    from orion_agent.harness.agent.pillars import QUERY_PILLAR, GENERATE_PILLAR

    assert "lookup_nasa_requirement" in QUERY_PILLAR.tools
    assert "lookup_nasa_requirement" in GENERATE_PILLAR.tools
