"""The production loop, pinned against a trace it actually produced.

``tests/fixtures/golden_trace_nema23.json`` was captured by running the real
``StudioAgent.design`` and ``StudioAgent.explain`` against the configured model
and the *deployed* FreeCAD builder, at commit b156d19. It carries the request,
the frozen Blueprint, what the kernel measured, every assertion, the verdict,
the topology sidecar, and every tool call with its arguments and the exact
observation the model was shown.

That makes the fixture self-contained, and these tests hermetic: no model, no
kernel, no container, no network. What they check is not "does the same string
come back" — a trace diffed byte for byte is a test that fails whenever anything
improves. They check the *invariants the architecture claims*, by recomputing
each one from the recorded evidence and, where it matters, by perturbing that
evidence and requiring the answer to move:

1. the Blueprint was frozen before the kernel ran, and nothing measured leaked in
2. the verdict is a function of evidence, not something the model wrote
3. an unaccounted dimension cannot produce VERIFIED
4. the inspection tools read the built artifact, not the conversation
5. a request missing required information is asked about, not guessed at
"""

import copy
import json
import math
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def trace() -> dict:
    """A complete successful turn: design, build, grade, inspect."""
    return _load("golden_trace_nema23.json")


@pytest.fixture(scope="module")
def clarification() -> dict:
    """A turn where the request did not say enough to build anything."""
    return _load("trace_clarification_nema23.json")


# --------------------------------------------------------------------------- #
# 1. the Blueprint was frozen before anything ran
# --------------------------------------------------------------------------- #
def test_the_blueprint_hash_verifies(trace):
    from orion.blueprint import Blueprint

    bp = Blueprint.from_dict(trace["blueprint"])
    assert bp.blueprint_hash == trace["blueprint_hash"]
    assert bp.verify_hash()


def test_refreezing_the_stored_payload_reproduces_the_hash(trace):
    """The contract is exactly what was hashed — no measurement leaked back in.

    If any part of the payload had been written after the build, re-freezing the
    stored payload would produce a different digest.
    """
    from orion.blueprint import Blueprint

    payload = dict(trace["blueprint"])
    payload.pop("blueprint_hash", None)
    assert (
        Blueprint.from_dict(payload).freeze().blueprint_hash == trace["blueprint_hash"]
    )


def test_the_frozen_contract_holds_expressions_not_measurements(trace):
    """Assertion targets are expressions over variables, resolved at build time.

    A target stored as the measured number would make every assertion pass by
    construction, which is the failure the freeze exists to prevent.
    """
    from orion.blueprint import Blueprint

    bp = Blueprint.from_dict(trace["blueprint"])
    measured_volume = trace["measurements"]["volume_mm3"]
    for assertion in bp.assertions:
        target = assertion.get("target")
        assert not isinstance(target, (int, float)) or target != measured_volume, (
            f"assertion {assertion.get('id')!r} stores a measured value as its target"
        )


# --------------------------------------------------------------------------- #
# 2. the verdict is derived from evidence
# --------------------------------------------------------------------------- #
def _regrade(trace: dict, rows=None, measured=None, design_plan=None):
    from orion_physical_ai import verify

    merged = dict(trace["verification"]["measured"])
    merged.update(measured or {})
    return verify.from_assertion_rows(
        rows if rows is not None else trace["assertions"],
        measured=merged,
        engineering=trace.get("engineering") or [],
        design_plan=(
            design_plan
            if design_plan is not None
            else trace["blueprint"]["design_plan"]
        ),
    )


def test_the_recorded_verdict_recomputes_from_the_recorded_evidence(trace):
    report = _regrade(trace)
    assert report["verdict"] == trace["verification"]["verdict"] == "verified"
    assert [c["id"] for c in report["checks"]] == [
        c["id"] for c in trace["verification"]["checks"]
    ]


def test_the_verdict_is_a_function_of_the_checks(trace):
    from orion_physical_ai import verify

    assert (
        verify.verdict_for(trace["verification"]["checks"])
        == trace["verification"]["verdict"]
    )


def test_a_failed_assertion_moves_the_verdict(trace):
    """Perturb the evidence and the answer has to move, or it was never derived
    from the evidence at all."""
    rows = [dict(r) for r in trace["assertions"]]
    rows[0]["passed"] = False
    assert _regrade(trace, rows=rows)["verdict"] == "refused"


def test_an_unsound_solid_moves_the_verdict(trace):
    assert _regrade(trace, measured={"valid": False})["verdict"] == "refused"


# --------------------------------------------------------------------------- #
# 3. an unaccounted dimension cannot produce VERIFIED
# --------------------------------------------------------------------------- #
def test_the_golden_part_is_fully_accounted_for(trace):
    from orion import provenance as P

    ledger = trace["blueprint"]["design_plan"]["provenance"]
    assert set(ledger) == set(trace["variables"])
    assert P.unsourced(ledger) == []
    assert P.summary(ledger) == {"stated": 4, "standard": 1}


def test_one_unsourced_dimension_takes_verified_away(trace):
    """The assertion this whole layer exists for. Geometry unchanged, every
    kernel check still passing, and the verdict must stop saying VERIFIED."""
    plan = copy.deepcopy(trace["blueprint"]["design_plan"])
    plan["provenance"]["L"] = {
        "source": "unsourced",
        "basis": "no number in the request accounts for this value",
    }

    report = _regrade(trace, design_plan=plan)

    assert report["verdict"] == "unsourced"
    # Not a refusal: the part is real and every geometry check still passed.
    assert report["failed"] == []
    assert all(
        c["status"] == "pass"
        for c in report["checks"]
        if not c["id"].startswith("provenance")
    )
    row = next(c for c in report["checks"] if c["id"].startswith("provenance"))
    assert row["status"] == "warn" and row["evidence"]["unsourced"] == ["L"]


def test_the_ledger_cannot_be_rewritten_after_the_freeze(trace):
    """A provenance record that could be edited to suit the result would prove
    nothing — the same reason the assertions are frozen."""
    from orion.blueprint import Blueprint

    tampered = copy.deepcopy(trace["blueprint"])
    tampered["design_plan"]["provenance"]["hole_r"] = {
        "source": "stated",
        "basis": "given in the request",
    }
    assert not Blueprint.from_dict(tampered).verify_hash()


# --------------------------------------------------------------------------- #
# 4. the inspection tools read the artifact, not the conversation
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def replayed(trace) -> list:
    """Every recorded tool call, re-executed against the recorded artifact."""
    from app.services.part_bridge import PartBridge
    from orion_agent.harness.tools.registry import build_part_registry

    bridge = PartBridge(
        request_id=trace["request_id"],
        part={
            "blueprint": trace["blueprint"],
            "part_class": trace["part_class"],
            "stats": trace["measurements"],
        },
    )
    # Injected, so the replay reads the geometry the trace carries rather than
    # whatever happens to be on this machine's disk.
    bridge._topology, bridge._topology_loaded = trace["topology"], True
    registry = build_part_registry(bridge)

    return [
        (call, registry.execute(call["tool"], call["arguments"]))
        for call in trace["inspection"]["tool_calls"]
    ]


def test_every_recorded_tool_call_replays_identically(replayed):
    """Same artifact in, same observation out. An observation that had come from
    the model rather than from geometry could not be reproduced from the
    artifact alone."""
    assert replayed, "the golden trace records no tool calls"
    for recorded, result in replayed:
        where = f"{recorded['tool']}{recorded['arguments']}"
        assert result.ok == recorded["ok"], where
        assert result.content == recorded["observation"], where


def test_the_tools_read_real_topology(trace, replayed):
    """The counts the model was given are the kernel's, not a paraphrase."""
    counts = trace["topology"]["counts"]
    observation = next(
        r.content for c, r in replayed if c["tool"] == "inspect_topology"
    )
    assert f"{counts['faces']} faces" in observation
    assert f"{counts['edges']} edges" in observation
    # Four M5 holes -> four cylindrical faces, in the kernel's own tally.
    cylinders = sum(
        1 for f in trace["topology"]["faces"] if f.get("surface") == "Cylinder"
    )
    assert cylinders == 4


def test_a_measurement_agrees_with_the_geometry_independently(trace, replayed):
    """The separation the tool reported is recomputable from the Blueprint's own
    variables — without the tool, and without the model."""
    separations = [
        r.raw["centroid_distance"]
        for c, r in replayed
        if c["tool"] == "measure" and (r.raw or {}).get("centroid_distance")
    ]
    assert separations, "no measurement recorded a centroid separation"

    v = trace["variables"]
    chord = 2 * v["pcd_r"] * math.sin(math.pi / 4)  # adjacent holes, four on a circle
    across = 2 * v["pcd_r"]  # diametrically opposite
    thickness = v["T"]
    assert any(
        s == pytest.approx(chord, rel=1e-4)
        or s == pytest.approx(across, rel=1e-4)
        or s == pytest.approx(thickness, rel=1e-4)
        for s in separations
    ), f"no recorded separation matches the geometry: {separations}"


def test_an_inexact_measurement_says_so_in_what_the_model_reads(replayed):
    """A bound presented as a distance is a number nobody would question."""
    checked = 0
    for recorded, result in replayed:
        if recorded["tool"] != "measure":
            continue
        if (result.raw or {}).get("exact") is False:
            assert "NOT an exact minimum distance" in result.content
            assert result.raw["lower_bound"] <= result.raw["centroid_distance"]
            checked += 1
    assert checked, "the golden trace records no inexact measurement to check"


def test_the_write_half_is_not_even_offered(trace):
    from app.services.part_bridge import PartBridge
    from orion_agent.harness.tools.registry import build_part_registry

    registry = build_part_registry(
        PartBridge(request_id="", part={"blueprint": trace["blueprint"]})
    )
    for name in (
        "set_parameter",
        "edit_feature",
        "write_code",
        "import_shape",
        "delete_object",
        "undo",
        "export",
    ):
        assert registry.get(name) is None, name


# --------------------------------------------------------------------------- #
# 5. the complete loop, and the refusal to guess
# --------------------------------------------------------------------------- #
def test_the_trace_covers_the_whole_loop(trace):
    """Every stage the product claims, present in one turn."""
    assert trace["route"]["route"]
    assert trace["blueprint_hash"]
    assert trace["build_ok"] is True
    assert trace["measurements"]["volume_mm3"] > 0
    assert trace["assertions"] and all(a["passed"] for a in trace["assertions"])
    assert trace["verification"]["verdict"]
    assert trace["inspection"]["inspected"] is True
    assert trace["inspection"]["answered"] is True
    assert len(trace["inspection"]["tool_calls"]) >= 3
    assert "built" in trace["design_events"]
    assert "verification" in trace["design_events"]


def test_a_request_that_does_not_say_enough_is_asked_about(clarification):
    """No Blueprint, no geometry, no invented dimensions — questions instead.

    The first line of defence, and it fires before provenance ever matters: the
    interview refuses to complete rather than filling the gap itself.
    """
    assert clarification["build_ok"] is False
    assert clarification["blueprint"] is None
    assert clarification["variables"] is None
    assert clarification["questions"]
    assert all(q.strip().endswith("?") for q in clarification["questions"])
    assert clarification["verification"] == {}


def test_the_fixtures_were_captured_from_a_committed_tree(trace, clarification):
    """A trace captured from a dirty tree describes code that exists nowhere."""
    for t in (trace, clarification):
        assert t["commit"] and not t["commit"].endswith("-dirty")
