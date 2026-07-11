"""Offline tests for the standards knowledge base (network-free, CI-safe).

Run with:  pytest orion_agent/tests/test_standards.py -v
"""

import pytest

from orion_agent.harness import standards as std
from orion_agent.harness.spec import SpecParser
from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.pillars import QUERY_PILLAR, GENERATE_PILLAR
from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel


# --------------------------------------------------------------------------- #
# table spot checks against catalogue values
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("des,bore,od,width", [
    ("608", 8, 22, 7),
    ("6204", 20, 47, 14),
    ("6005", 25, 47, 12),
    ("32005", 25, 47, 15),
    ("30204", 20, 47, 15.25),
])
def test_bearing_values(des, bore, od, width):
    row = std.BEARINGS[des]
    assert (row["bore"], row["od"], row["width"]) == (bore, od, width)


def test_fastener_values():
    m5 = std.FASTENERS["M5"]
    assert m5["clearance_normal"] == 5.5
    assert m5["tap_drill"] == 4.2
    assert m5["shcs_head_d"] == 8.5
    assert m5["nut_af"] == 8.0
    assert std.FASTENERS["M8"]["pitch"] == 1.25


def test_nema_values():
    n17, n23 = std.NEMA[17], std.NEMA[23]
    assert n17["bolt_spacing"] == 31.0 and n17["pilot_d"] == 22.0
    assert n23["bolt_spacing"] == 47.14 and n23["pilot_d"] == 38.1


# --------------------------------------------------------------------------- #
# detection / search
# --------------------------------------------------------------------------- #
def test_detect_designation_nema_and_thread():
    hits = std.detect("housing for a 6204 bearing on a NEMA 17 motor with M3 screws")
    kinds = {h["kind"]: h for h in hits}
    assert kinds["bearing"]["designation"] == "6204"
    assert kinds["nema"]["designation"] == "NEMA 17"
    assert kinds["fastener"]["designation"] == "M3"


def test_detect_bore_candidates_formula_student():
    msg = ("Design a Formula Student suspension upright machined from 7075-T6 "
           "aluminum. It must support a 20 mm wheel axle with tapered roller "
           "bearings and mount a four-piston brake caliper.")
    hits = std.detect(msg)
    bearings = [h for h in hits if h["kind"] == "bearing"]
    assert bearings and all(h["candidate"] for h in bearings)
    assert {h["designation"] for h in bearings} == {"30204", "32004"}
    assert all(h["bore"] == 20 for h in bearings)


def test_detect_no_false_positive_on_alloys():
    hits = std.detect("a bracket in 6061-T6 aluminum, 2024 alloy alternative")
    assert hits == []


def test_search_type_browse_and_bore():
    hits = std.search("deep groove ball bearing bore 25")
    assert {h["designation"] for h in hits} <= {"6005", "6205", "6305"}
    assert len(hits) >= 2
    hits2 = std.search("tapered roller bearings")
    assert hits2 and all(h["type"] == "tapered roller" for h in hits2)
    assert std.search("a poem about gears") == []


def test_render_is_compact_lines():
    text = std.render(std.detect("6204 bearing, M5 screws"))
    assert "bore 20 mm x OD 47 mm" in text
    assert "clearance hole 5.5 mm" in text


# --------------------------------------------------------------------------- #
# spec-stage auto-attach
# --------------------------------------------------------------------------- #
def test_spec_attaches_standards_and_renders():
    spec = SpecParser(llm=None).parse(
        "Design a NEMA 23 stepper mount plate, 6 mm thick, with M5 screws.")
    kinds = {s["kind"] for s in spec.standards}
    assert kinds == {"nema", "fastener"}
    rendered = spec.render()
    assert "47.14" in rendered and "38.1" in rendered
    assert "authoritative" in rendered
    # retrieved numbers live in standards, never in grounded dimensions
    assert 47.14 not in spec.dimensions.values()


def test_spec_standards_not_grounding_stripped():
    # The user never typed 47 mm; the bearing OD must still survive.
    spec = SpecParser(llm=None).parse("a housing for a 6204 bearing")
    assert spec.standards[0]["od"] == 47
    assert not spec.is_empty()


# --------------------------------------------------------------------------- #
# tool + pillar wiring
# --------------------------------------------------------------------------- #
def test_lookup_standard_tool():
    reg = build_registry(SyntheticBridge(SyntheticModel(name="X")), sandbox=None)
    res = reg.execute("lookup_standard", {"query": "6204"})
    assert res.ok and "47" in res.content
    miss = reg.execute("lookup_standard", {"query": "flux capacitor"})
    assert not miss.ok


def test_all_pillars_can_lookup():
    assert "lookup_standard" in QUERY_PILLAR.tools
    assert "lookup_standard" in GENERATE_PILLAR.tools
