"""A requested feature that is not in the solid must never grade VERIFIED.

The defect these tests exist for was reproduced end to end: a request stating
``hole_count = 4`` and ``hole_d = 5`` with no bolt circle built a **blank
plate**, and every existing check agreed with it. The extents matched. The solid
was sound. The closed-form volume matched the kernel to zero relative error —
because the closed form was computed from the same absent holes. And
``blueprint_gen``'s consumption guard stayed quiet, because the builder *read*
``hole_count`` and ``hole_r`` before deciding it could not place them, so
``_Seen`` recorded them as used.

That is why feature fulfillment has to be an independent dimension of the
verdict rather than a consequence of the others. Every assertion in this file is
about geometry the kernel produced, taken from the topology sidecar — the one
account of the part that was not derived from the requirements.

The fixture is a real build: FreeCAD 1.1.3 producing a 120 x 80 x 10 plate with
four 5.5 mm-radius holes on a 47.14 mm bolt circle, trimmed to the faces the
assertions use. The adversarial variants are that record with one fact changed.
"""

import copy

import pytest

from orion import fulfillment as F
from orion import obligations as O
from orion_physical_ai import verify

# --------------------------------------------------------------------------- #
# the geometry
# --------------------------------------------------------------------------- #
PCD_R = 23.57
HOLE_R = 2.75

#: The four bolt-circle axes, as FreeCAD reported them.
AXES = [
    (23.57, 0.0),
    (0.0, 23.57),
    (-23.57, 0.0),
    (0.0, -23.57),
]


def _cyl(index: int, radius: float, x: float, y: float) -> dict:
    return {
        "ref": f"#o1.s1.f{index}",
        "index": index,
        "element": f"Face{index}",
        "feature": "plate",
        "surface": "Cylinder",
        "radius": radius,
        "axis": [0.0, 0.0, -1.0],
        "position": [x, y, 0.0],
        "area": 2 * 3.14159265 * radius * 10.0,
        "center": [x, y, 5.0],
        "bbox": [x - radius, y - radius, 0.0, x + radius, y + radius, 10.0],
        "stable": f"@plate.f{index}",
    }


def _plane(index: int, normal: list, centre: list, bbox: list) -> dict:
    return {
        "ref": f"#o1.s1.f{index}",
        "index": index,
        "element": f"Face{index}",
        "feature": "plate",
        "surface": "Plane",
        "normal": normal,
        "position": centre,
        "center": centre,
        "bbox": bbox,
        "stable": f"@plate.f{index}",
    }


def _topology(holes: list) -> dict:
    """A 120 x 80 x 10 plate carrying exactly the holes given."""
    faces = [
        _plane(1, [0.0, -1.0, 0.0], [0.0, -40.0, 5.0], [-60, -40, 0, 60, -40, 10]),
        _plane(2, [1.0, 0.0, 0.0], [60.0, 0.0, 5.0], [60, -40, 0, 60, 40, 10]),
        _plane(3, [0.0, 1.0, 0.0], [0.0, 40.0, 5.0], [-60, 40, 0, 60, 40, 10]),
        _plane(4, [-1.0, 0.0, 0.0], [-60.0, 0.0, 5.0], [-60, -40, 0, -60, 40, 10]),
        _plane(5, [0.0, 0.0, -1.0], [0.0, 0.0, 0.0], [-60, -40, 0, 60, 40, 0]),
        _plane(6, [0.0, 0.0, 1.0], [0.0, 0.0, 10.0], [-60, -40, 10, 60, 40, 10]),
    ]
    faces += [_cyl(7 + i, r, x, y) for i, (r, x, y) in enumerate(holes)]
    return {
        "schema": "orionflow-topology-v1",
        "attribution": "element_map",
        "occurrences": [
            {
                "ref": "#o1",
                "name": "Body",
                "label": "Body",
                "shape": "#o1.s1",
                "bbox": [-60.0, -40.0, 0.0, 60.0, 40.0, 10.0],
            }
        ],
        "faces": faces,
        "edges": [],
        "vertices": [],
        "features": {"plate": {"type": "PartDesign::Pad", "label": "plate",
                               "build_index": 0, "faces": [f["ref"] for f in faces],
                               "edges": [], "vertices": []}},
        "counts": {"faces": len(faces), "edges": 0, "vertices": 0,
                   "features": 1, "unattributed": 0},
        "truncated": [],
    }


CORRECT = _topology([(HOLE_R, x, y) for x, y in AXES])
BLANK = _topology([])
THREE_HOLES = _topology([(HOLE_R, x, y) for x, y in AXES[:3]])
WRONG_DIAMETER = _topology([(3.0, x, y) for x, y in AXES])
WRONG_PCD = _topology([(HOLE_R, x * 1.4, y * 1.4) for x, y in AXES])


# --------------------------------------------------------------------------- #
# obligations come from the request, not from the builder's output
# --------------------------------------------------------------------------- #
def test_a_stated_hole_pattern_creates_an_obligation_even_with_no_position():
    """The defect case exactly: count and diameter given, bolt circle absent.

    The obligation still exists. A rule that needed all three would go quiet at
    precisely the moment the builder does, which is what made this invisible.
    """
    obligations = O.derive(
        "rect_plate",
        {"length": 120, "width": 80, "thickness": 10, "hole_count": 4, "hole_r": 2.5},
    )
    assert [o.id for o in obligations] == ["bolt_circle"]
    holes = obligations[0]
    assert holes.count == 4 and holes.radius == 2.5
    assert holes.placement is None  # nothing said where — still owed, still unplaced


def test_a_request_with_no_features_obliges_nothing():
    assert O.derive("rect_plate", {"length": 120, "width": 80, "thickness": 10}) == []


def test_the_obligation_is_frozen_into_the_contract():
    """Inside ``blueprint_hash``, so it cannot be dropped after measurement."""
    from orion import blueprint_gen, interview
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="a plate", family="rect_plate")
    iv.slots = {"length": 120, "width": 80, "thickness": 10,
                "hole_count": 4, "hole_d": 5}
    iv.classify()
    bp = Blueprint.from_dict(
        blueprint_gen.generate("rect_plate", interview.requirements(iv))
    ).freeze()

    obligations = bp.design_plan["obligations"]
    assert [o["id"] for o in obligations] == ["bolt_circle"]
    assert obligations[0]["count"] == 4

    tampered = copy.deepcopy(bp.to_dict())
    tampered["design_plan"]["obligations"] = []
    assert not Blueprint.from_dict(tampered).verify_hash()


# --------------------------------------------------------------------------- #
# reading the geometry
# --------------------------------------------------------------------------- #
def test_axes_are_counted_not_faces():
    assert len(F.cylinder_axes(CORRECT, HOLE_R)) == 4
    assert F.cylinder_axes(BLANK, HOLE_R) == []


def test_coaxial_faces_are_one_hole():
    """A counterbore is two cylindrical faces on one axis, not two holes."""
    counterbored = _topology(
        [(HOLE_R, x, y) for x, y in AXES] + [(HOLE_R, AXES[0][0], AXES[0][1])]
    )
    assert len(F.cylinder_axes(counterbored, HOLE_R)) == 4


def test_holes_drilled_along_x_are_counted_correctly():
    """An L-bracket's bolt pattern runs along X, not Z.

    The first detector projected every anchor onto XY, which is right only for
    holes drilled along Z. Four real holes at (y, z) = (±20, 20) and (±20, 60)
    share two XY points, so it reported "4 requested, 2 found" and refused a
    part FreeCAD had built perfectly. Geometry from a real l_bracket build.
    """
    faces = [
        _cyl(1, 4.2, 0, 0) | {"axis": [1.0, 0.0, 0.0],
                              "position": [8.0, 20.0, 20.0]},
        _cyl(2, 4.2, 0, 0) | {"axis": [1.0, 0.0, 0.0],
                              "position": [8.0, 20.0, 60.0]},
        _cyl(3, 4.2, 0, 0) | {"axis": [1.0, 0.0, 0.0],
                              "position": [8.0, -20.0, 20.0]},
        _cyl(4, 4.2, 0, 0) | {"axis": [1.0, 0.0, 0.0],
                              "position": [8.0, -20.0, 60.0]},
    ]
    bracket = _topology([])
    bracket["faces"] = faces
    bracket["occurrences"][0]["bbox"] = [0.0, -30.0, 0.0, 100.0, 30.0, 80.0]

    assert len(F.cylinder_axes(bracket, 4.2)) == 4

    square = [
        O.Obligation(id="bolt_square", kind=O.HOLE_PATTERN,
                     label="mounting hole pattern", count=4, radius=4.2,
                     placement={"form": O.GRID, "pitch": [40.0, 40.0]},
                     source=("hole_r", "bolt_square"))
    ]
    row = F.check(square, bracket)[0]
    assert row["status"] == "pass", row["detail"]
    assert row["verified"] is True


def test_a_pattern_on_the_wrong_pitch_still_fails_off_axis():
    """The axis fix must not have made placement unfalsifiable."""
    faces = [
        _cyl(i, 4.2, 0, 0) | {"axis": [1.0, 0.0, 0.0], "position": [8.0, y, z]}
        for i, (y, z) in enumerate([(30, 15), (30, 65), (-30, 15), (-30, 65)], 1)
    ]
    bracket = _topology([])
    bracket["faces"] = faces
    bracket["occurrences"][0]["bbox"] = [0.0, -30.0, 0.0, 100.0, 30.0, 80.0]

    square = [
        O.Obligation(id="bolt_square", kind=O.HOLE_PATTERN,
                     label="mounting hole pattern", count=4, radius=4.2,
                     placement={"form": O.GRID, "pitch": [40.0, 40.0]},
                     source=("hole_r", "bolt_square"))
    ]
    assert F.check(square, bracket)[0]["status"] == "fail"


# --------------------------------------------------------------------------- #
# the five adversarial cases
# --------------------------------------------------------------------------- #
def _obligation(count=4, radius=HOLE_R, pcd=PCD_R) -> list:
    placement = {"form": O.BOLT_CIRCLE, "radius": pcd} if pcd else None
    return [
        O.Obligation(
            id="bolt_circle",
            kind=O.HOLE_PATTERN,
            label="mounting hole pattern",
            count=count,
            radius=radius,
            placement=placement,
            source=("hole_count", "hole_r", "pcd_r"),
        )
    ]


def test_1_missing_feature_is_not_fulfilled():
    """Requested 4 holes, built 0."""
    rows = F.check(_obligation(), BLANK)
    assert rows[0]["status"] == "fail"
    assert rows[0]["observed"] is False and rows[0]["verified"] is False
    assert "contains none" in rows[0]["detail"]


def test_2_wrong_count_is_not_fulfilled():
    """Requested 4 holes, built 3."""
    rows = F.check(_obligation(), THREE_HOLES)
    assert rows[0]["status"] == "fail"
    assert rows[0]["observed"] is True  # geometry exists…
    assert rows[0]["verified"] is False  # …and it is the wrong geometry
    assert "3 were found" in rows[0]["detail"]


def test_3_wrong_diameter_is_not_fulfilled():
    """Requested 5.5 mm radius, built 3.0 mm."""
    rows = F.check(_obligation(), WRONG_DIAMETER)
    assert rows[0]["status"] == "fail"
    assert rows[0]["evidence"]["cylindrical_radii_present_mm"] == [3.0]


def test_4_wrong_placement_is_not_fulfilled():
    """Four holes of the right size, on the wrong bolt circle."""
    rows = F.check(_obligation(), WRONG_PCD)
    assert rows[0]["status"] == "fail"
    assert "placement does not agree" in rows[0]["detail"]
    assert rows[0]["evidence"]["expected_radius_mm"] == PCD_R


def test_the_correct_part_is_fulfilled():
    rows = F.check(_obligation(), CORRECT)
    assert rows[0]["status"] == "pass"
    assert rows[0]["verified"] is True


def test_count_and_diameter_still_bind_when_no_placement_was_stated():
    """The defect case's own obligation: unplaced, but not unenforced."""
    unplaced = _obligation(pcd=None)
    assert F.check(unplaced, BLANK)[0]["status"] == "fail"
    assert F.check(unplaced, THREE_HOLES)[0]["status"] == "fail"
    # Right count and size, on a circle nobody specified — nothing to contradict.
    passed = F.check(unplaced, WRONG_PCD)[0]
    assert passed["status"] == "pass"
    assert "fixed no position" in passed["detail"]


# --------------------------------------------------------------------------- #
# 5. the verdict gate — geometry otherwise perfect
# --------------------------------------------------------------------------- #
PASSING_ROWS = [
    {"kind": "bbox_extent", "id": "len", "passed": True, "target": 120.0,
     "measured": 120.0, "rel_err": 0.0, "tier": 1},
    {"kind": "body_volume", "id": "body", "passed": True, "target": 95049.67,
     "measured": 95049.67, "rel_err": 0.0, "tier": 1},
]
CLEAN_LEDGER = {
    "L": {"source": "stated", "basis": "given in the request"},
    "W": {"source": "stated", "basis": "given in the request"},
    "T": {"source": "stated", "basis": "given in the request"},
}


def _report(topology, obligations=None, ledger=None):
    plan = {"provenance": ledger if ledger is not None else CLEAN_LEDGER}
    if obligations is not None:
        plan["obligations"] = obligations
    return verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1, "watertight": True},
        design_plan=plan,
        topology=topology,
    )


def test_5_a_geometrically_perfect_part_missing_its_feature_is_not_verified():
    """Extents pass. Solid validity passes. Volume passes. Ledger passes.

    The requested feature is absent, and that alone must take VERIFIED away.
    This is the whole argument for feature fulfillment being an independent
    dimension: nothing else in the report can see the difference, because
    everything else was derived from the same requirements the feature was.
    """
    perfect = _report(CORRECT, obligations=O.to_dicts(_obligation()))
    assert perfect["verdict"] == verify.VERIFIED

    missing = _report(BLANK, obligations=O.to_dicts(_obligation()))
    assert missing["verdict"] != verify.VERIFIED
    assert missing["verdict"] == verify.REFUSED

    # …and every other check still passed, which is the point.
    others = [c for c in missing["checks"] if not c["id"].startswith("feature:")]
    assert others and all(c["status"] == verify.PASS for c in others)

    failed = missing["failed"]
    assert [c["id"] for c in failed] == ["feature:bolt_circle"]


@pytest.mark.parametrize(
    "topology,why",
    [
        (BLANK, "missing"),
        (THREE_HOLES, "wrong count"),
        (WRONG_DIAMETER, "wrong diameter"),
        (WRONG_PCD, "wrong placement"),
    ],
)
def test_every_adversarial_case_refuses_at_the_verdict(topology, why):
    report = _report(topology, obligations=O.to_dicts(_obligation()))
    assert report["verdict"] == verify.REFUSED, why


# --------------------------------------------------------------------------- #
# 6. evidence tampering
# --------------------------------------------------------------------------- #
def test_6_removing_the_topology_evidence_prevents_verified():
    """Ledger untouched, contract untouched, evidence gone.

    "No fulfillment evidence" must resolve to "not verified", never to
    "verified" — otherwise a build whose sidecar failed to write would grade
    better than one that was actually checked.
    """
    report = _report(None, obligations=O.to_dicts(_obligation()))
    assert report["verdict"] != verify.VERIFIED
    row = next(c for c in report["checks"] if c["id"] == "feature:bolt_circle")
    assert row["status"] == verify.WARN
    assert "could not be checked" in row["detail"]


def test_6b_emptied_topology_is_not_a_pass():
    emptied = copy.deepcopy(CORRECT)
    emptied["faces"] = []
    report = _report(emptied, obligations=O.to_dicts(_obligation()))
    assert report["verdict"] != verify.VERIFIED


def test_6c_altered_topology_is_caught(trace_free=None):
    """Change the evidence and the verdict changes with it."""
    altered = copy.deepcopy(CORRECT)
    for face in altered["faces"]:
        if face.get("surface") == "Cylinder":
            face["radius"] = 9.0
    assert _report(altered, obligations=O.to_dicts(_obligation()))["verdict"] == (
        verify.REFUSED
    )


def test_the_model_cannot_supply_fulfillment_evidence():
    """There is no path from a completion into a fulfillment record.

    ``check`` takes obligations and a topology record and nothing else — no
    bundle, no answer, no narrative. The only way to make it say "four holes
    exist" is for four holes to exist.
    """
    import inspect

    signature = inspect.signature(F.check)
    assert list(signature.parameters) == ["obligations", "topology", "template"]

    narrated = {"answer": "there are four holes", "tool_calls": []}
    rows = F.check(_obligation(), BLANK, template=narrated)
    assert rows[0]["status"] == "fail"


# --------------------------------------------------------------------------- #
# what must not have changed
# --------------------------------------------------------------------------- #
def test_a_design_that_obliged_nothing_is_unaffected():
    """Every part built before this existed, and every model-authored one."""
    assert verify.fulfillment_rows({}, CORRECT) == []
    assert verify.fulfillment_rows({"provenance": CLEAN_LEDGER}, None) == []
    report = _report(CORRECT)  # no obligations key at all
    assert report["verdict"] == verify.VERIFIED
    assert not any(c["id"].startswith("feature:") for c in report["checks"])


def test_a_failing_assertion_still_outranks_a_fulfilled_feature():
    rows = [dict(r) for r in PASSING_ROWS]
    rows[0]["passed"] = False
    report = verify.from_assertion_rows(
        rows,
        measured={"valid": True, "solids": 1},
        design_plan={"provenance": CLEAN_LEDGER,
                     "obligations": O.to_dicts(_obligation())},
        topology=CORRECT,
    )
    assert report["verdict"] == verify.REFUSED


def test_the_fulfillment_records_travel_with_the_report():
    report = _report(BLANK, obligations=O.to_dicts(_obligation()))
    assert report["fulfillment"]
    record = report["fulfillment"][0]
    # The four states, kept apart.
    assert record["requested"] is True
    assert record["instantiated"] is True  # the solid exists…
    assert record["observed"] is False  # …without the feature
    assert record["verified"] is False
