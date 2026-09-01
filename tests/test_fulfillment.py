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
    # A placement is part of asking for holes: without one the interview is
    # incomplete, which is the defect this module exists for — this fixture
    # used to state a count and a size and nothing else, and that is precisely
    # the request that built a blank plate.
    iv.slots = {"length": 120, "width": 80, "thickness": 10,
                "hole_count": 4, "hole_d": 5, "hole_edge_gap": 10}
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
# the dressings: silent until obligations reached them
# --------------------------------------------------------------------------- #
#
# Every geometric signature below was read off a real FreeCAD 1.1.3 build, not
# assumed. A 160 x 120 plate with an 8 mm corner radius leaves four cylinders of
# radius 8.0 at (+/-72, +/-52); a 6 mm inside fillet on an L-bracket leaves
# exactly one cylinder of radius 6.0 with its axis along the width; a 2 mm
# chamfer leaves eight oblique planes and an `edge_chamfer` feature whose *size*
# this system cannot recover — so it warns rather than claiming.


def _dressed(radius: float, points: list, axis=(0.0, 0.0, -1.0)) -> dict:
    """A plate carrying rounds of ``radius`` at the given axis anchors."""
    topology = _topology([])
    faces = list(topology["faces"])
    for i, (x, y, z) in enumerate(points, start=len(faces) + 1):
        faces.append(
            _cyl(i, radius, x, y) | {"axis": list(axis), "position": [x, y, z]}
        )
    topology["faces"] = faces
    return topology


#: L=160, W=120, r=8 -> axes at (+/-72, +/-52), spanning 144 x 104.
CORNERS_8 = _dressed(8.0, [(72, -52, 0), (72, 52, 0), (-72, 52, 0), (-72, -52, 0)])
NO_CORNERS = _topology([])


def _round_obligation(oid="corner_radius", label="rounded corners", radius=8.0,
                      count=4, pitch=(144.0, 104.0)):
    placement = {"form": O.GRID, "pitch": list(pitch)} if pitch else None
    return [
        O.Obligation(id=oid, kind=O.ROUND, label=label, count=count,
                     radius=radius, placement=placement,
                     source=("corner_radius",))
    ]


def _dressing_obligation(oid="chamfer", label="edge chamfer",
                         expect=("Chamfer",)):
    return [
        O.Obligation(id=oid, kind=O.DRESSING, label=label, source=("chamfer",),
                     expect_feature=expect)
    ]


def _with_features(topology: dict, features: dict) -> dict:
    out = copy.deepcopy(topology)
    out["features"] = {**out.get("features", {}), **features}
    return out


CHAMFERED = _with_features(
    CORRECT,
    {"edge_chamfer": {"type": "PartDesign::Chamfer", "label": "edge_chamfer",
                      "build_index": 1, "faces": ["#o1.s1.f20"], "edges": [],
                      "vertices": []}},
)
UNCHAMFERED = CORRECT


# ---- corner radius / external fillet: measurable, so omission is a FAIL ---- #
def test_a_corner_radius_that_was_built_verifies():
    row = F.check(_round_obligation(), CORNERS_8)[0]
    assert row["status"] == "pass" and row["verified"] is True


def test_a_corner_radius_the_builder_dropped_fails():
    """The silent path this closes: requested, absent, and until now invisible."""
    row = F.check(_round_obligation(), NO_CORNERS)[0]
    assert row["status"] == "fail"
    assert row["observed"] is False and row["verified"] is False


def test_a_corner_radius_built_at_the_wrong_size_fails():
    wrong = _dressed(5.0, [(75, -55, 0), (75, 55, 0), (-75, 55, 0), (-75, -55, 0)])
    assert F.check(_round_obligation(), wrong)[0]["status"] == "fail"


def test_a_corner_radius_on_the_wrong_footprint_fails():
    """Right radius, wrong inset — a rounded corner in the wrong place."""
    shifted = _dressed(8.0, [(50, -30, 0), (50, 30, 0), (-50, 30, 0), (-50, -30, 0)])
    assert F.check(_round_obligation(), shifted)[0]["status"] == "fail"


def test_an_inside_fillet_is_measured_on_its_own_axis():
    """One cylinder, axis along Y — the geometry a real l_bracket produces."""
    bracket = _topology([])
    bracket["faces"] = [
        _cyl(1, 6.0, 0, 0) | {"axis": [0.0, 1.0, 0.0],
                              "position": [16.0, -40.0, 16.0]}
    ]
    obligation = [
        O.Obligation(id="inside_fillet", kind=O.ROUND,
                     label="inside fillet at the joint", count=1, radius=6.0,
                     source=("inside_fillet",))
    ]
    assert F.check(obligation, bracket)[0]["status"] == "pass"
    assert F.check(obligation, _topology([]))[0]["status"] == "fail"


def test_a_shoulder_is_measured_as_the_step_it_leaves():
    """A 4 mm shoulder on a 26 mm seat leaves a 22 mm cylinder."""
    stepped = _dressed(22.0, [(0, 0, 0)])
    obligation = [
        O.Obligation(id="shoulder", kind=O.ROUND, label="locating shoulder",
                     count=1, radius=22.0, source=("shoulder",))
    ]
    assert F.check(obligation, stepped)[0]["status"] == "pass"
    assert F.check(obligation, _topology([]))[0]["status"] == "fail"


# ---- chamfer: existence checkable, size not — WARN, never PASS ------------- #
def test_a_chamfer_that_exists_warns_rather_than_verifying():
    """Rule B: attribution is not measurement, and must not be dressed as it."""
    row = F.check(_dressing_obligation(), CHAMFERED)[0]
    assert row["status"] == "warn"
    assert row["instantiated"] is True and row["observed"] is True
    assert row["verified"] is False
    assert "cannot independently measure" in row["detail"]


def test_a_chamfer_the_builder_dropped_fails():
    row = F.check(_dressing_obligation(), UNCHAMFERED)[0]
    assert row["status"] == "fail"
    assert row["instantiated"] is False


def test_a_present_chamfer_still_prevents_verified():
    """Rule C: the boundary stops VERIFIED without calling the geometry wrong."""
    report = _report(CHAMFERED, obligations=O.to_dicts(_dressing_obligation()))
    assert report["verdict"] == verify.UNSOURCED
    assert report["failed"] == []


def test_a_dropped_chamfer_refuses():
    report = _report(UNCHAMFERED, obligations=O.to_dicts(_dressing_obligation()))
    assert report["verdict"] == verify.REFUSED


def test_a_fillet_feature_is_matched_by_its_own_type_not_a_pocket():
    """The dispatcher once sent every non-cylindrical obligation looking for a
    Pocket, so a real fillet read as "dropped". Types are matched explicitly."""
    filleted = _with_features(
        CORRECT,
        {"edge_fillet": {"type": "PartDesign::Fillet", "label": "edge_fillet",
                         "build_index": 1, "faces": ["#o1.s1.f30"], "edges": [],
                         "vertices": []}},
    )
    obligation = _dressing_obligation("fillet", "external fillet", ("Fillet",))
    assert F.check(obligation, filleted)[0]["status"] == "warn"
    assert F.check(obligation, CORRECT)[0]["status"] == "fail"


# ---- every dressing is in the contract BEFORE the builder runs ------------- #
@pytest.mark.parametrize(
    "family,slots,expected_ids",
    [
        ("rect_plate", {"length": 160, "width": 120, "thickness": 16,
                        "corner_radius": 8}, ["corner_radius"]),
        ("rect_plate", {"length": 160, "width": 120, "thickness": 16,
                        "fillet": 6}, ["fillet"]),
        ("rect_plate", {"length": 160, "width": 120, "thickness": 16,
                        "chamfer": 2}, ["chamfer"]),
        ("l_bracket", {"base_length": 120, "base_width": 80,
                       "base_thickness": 10, "upright_height": 90,
                       "upright_thickness": 10, "inside_fillet": 6},
         ["inside_fillet"]),
        ("l_bracket", {"base_length": 120, "base_width": 80,
                       "base_thickness": 10, "upright_height": 90,
                       "upright_thickness": 10, "chamfer": 2}, ["chamfer"]),
        ("bearing_housing", {"length": 160, "width": 110, "height": 70,
                             "bore_d": 52, "seat_depth": 20, "shoulder": 4},
         ["bearing_seat", "shoulder"]),
        ("bearing_housing", {"length": 160, "width": 110, "height": 70,
                             "bore_d": 52, "seat_depth": 20, "chamfer": 2},
         ["bearing_seat", "chamfer"]),
        ("manifold", {"length": 120, "width": 60, "height": 40,
                      "passage_d": 16, "chamfer": 2},
         ["main_passage", "chamfer"]),
    ],
)
def test_the_obligation_exists_in_the_frozen_blueprint_before_any_build(
    family, slots, expected_ids
):
    """Rule A: derived from the requirement, present before the builder runs.

    Nothing here touches a kernel — the assertion is that the contract already
    names the feature at the moment it is hashed, which is what makes a later
    omission detectable at all.
    """
    from orion import blueprint_gen, interview
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="x", family=family)
    iv.slots, iv.notes = interview.apply_standards(dict(slots), family)
    iv.classify()
    bp = Blueprint.from_dict(
        blueprint_gen.generate(family, interview.requirements(iv))
    ).freeze()

    ids = [o["id"] for o in bp.design_plan["obligations"]]
    assert ids == expected_ids
    assert bp.verify_hash()

    tampered = copy.deepcopy(bp.to_dict())
    tampered["design_plan"]["obligations"] = []
    assert not Blueprint.from_dict(tampered).verify_hash()


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


# --------------------------------------------------------------------------- #
# the model-authored path declares that it cannot check features
# --------------------------------------------------------------------------- #
def test_a_model_authored_design_cannot_reach_verified_on_features():
    """An empty obligation list and "no way to know" are not the same claim.

    The compiled path derives obligations from typed requirements. A model
    authoring a Blueprint from prose produces none — and it also authors its own
    volume assertion, so a feature it silently dropped is missing from the
    geometry *and* from the prediction, and the two still agree. That is the
    exact shape of the defect obligations exist to catch, so the path says so
    instead of grading as though it had been checked.
    """
    plan = {
        "provenance": CLEAN_LEDGER,
        "feature_verification": {
            "available": False,
            "path": "model_authored",
            "reason": "authored by a model from prose, so no feature "
            "obligations exist",
        },
    }
    report = verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1, "watertight": True},
        design_plan=plan,
        topology=CORRECT,
    )
    assert report["verdict"] != verify.VERIFIED
    assert report["verdict"] == verify.UNSOURCED
    # Not a refusal — the geometry is sound, it is the feature claim that is
    # unavailable.
    assert report["failed"] == []
    row = next(c for c in report["checks"] if c["id"] == "feature:feature_verification")
    assert row["status"] == verify.WARN


def test_the_declaration_is_frozen_with_the_rest_of_the_contract():
    from app.services.studio_agent import _with_provenance
    from orion.blueprint import Blueprint

    payload = {
        "part_class": "widget",
        "variables": {"L": 40.0},
        "datums": {},
        "design_plan": {},
        "assertions": [{"id": "x", "kind": "bbox_extent", "axis": "x",
                        "tier": 1, "tol_rel": 1e-6, "target": "L"}],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad", "parameters": {"Length": "L"}},
            ],
            "sketches": [{"id": "s", "plane": "XY",
                          "profile": {"builder": "rect",
                                      "args": {"w": "L", "h": "L"}}}],
            "dependencies": [{"source": "s", "target": "pad", "kind": "profile"}],
        },
    }
    stamped = _with_provenance(payload, "a 40 mm widget")
    assert stamped["design_plan"]["feature_verification"]["available"] is False

    bp = Blueprint.from_dict(stamped).freeze()
    assert bp.verify_hash()

    tampered = copy.deepcopy(bp.to_dict())
    tampered["design_plan"].pop("feature_verification")
    assert not Blueprint.from_dict(tampered).verify_hash()


def test_the_compiled_path_makes_no_such_declaration():
    """It has typed requirements, so it derives real obligations instead."""
    from orion import blueprint_gen, interview
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="a plate 120 x 80 x 10 mm", family="rect_plate")
    iv.slots = {"length": 120, "width": 80, "thickness": 10}
    iv.classify()
    bp = Blueprint.from_dict(
        blueprint_gen.generate("rect_plate", interview.requirements(iv))
    ).freeze()
    assert "feature_verification" not in bp.design_plan
    assert bp.design_plan["obligations"] == []


# --------------------------------------------------------------------------- #
# unsupported: asked for, not in the vocabulary, and never silently gone
# --------------------------------------------------------------------------- #
#
# The last silent-loss path. ``_known_slots`` dropped anything the schema does
# not declare, so a requested draft angle or shell thickness vanished between
# the model's reply and the contract — and downstream "unsupported" looked
# exactly like "nobody asked for anything".
#
# Three states that must stay distinct:
#     unsupported  the request named it, and this system has no way to make it
#     omitted      the request named it, a builder exists, and it is not there
#     absent       nobody asked

UNSUPPORTED_DRAFT = [
    {
        "feature": "draft_angle",
        "requested": 3,
        "source": "interview",
        "reason": "no slot in part_families.yaml, so no builder and no observer",
    }
]


def test_an_unrecognised_feature_is_returned_not_discarded():
    from orion import interview

    slots, unsupported = interview._known_slots(
        "rect_plate",
        {"length": 120, "width": 80, "thickness": 10,
         "draft_angle": 3, "shell": 2},
    )
    assert slots == {"length": 120, "width": 80, "thickness": 10}
    assert [u["feature"] for u in unsupported] == ["draft_angle", "shell"]
    assert all(u["reason"] for u in unsupported)
    assert all(u["requested"] is not None for u in unsupported)


def test_request_metadata_is_not_reported_as_a_missing_capability():
    """Rule 4: do not manufacture capability reports out of model chatter.

    A ``notes`` field is a remark about the request, not a feature nobody can
    build, and burying the real one under it would be its own failure.
    """
    from orion import interview

    _slots, unsupported = interview._known_slots(
        "rect_plate",
        {"length": 120, "width": 80, "thickness": 10,
         "notes": "customer prefers anodised", "confidence": "high",
         "description": "a long sentence of prose about the part in question"},
    )
    assert unsupported == []


def test_a_supported_feature_is_never_reported_as_unsupported():
    """Rule 4, the other direction: chamfer has a slot, so it is not this."""
    from orion import interview

    slots, unsupported = interview._known_slots(
        "rect_plate", {"length": 120, "width": 80, "thickness": 10, "chamfer": 2}
    )
    assert slots["chamfer"] == 2
    assert unsupported == []


# ---- A: it survives into the frozen contract ------------------------------ #
def test_an_unsupported_feature_survives_into_the_frozen_blueprint():
    from orion import blueprint_gen, interview
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="a plate with a 3 degree draft",
                             family="rect_plate")
    iv.slots = {"length": 120, "width": 80, "thickness": 10}
    iv.unsupported = list(UNSUPPORTED_DRAFT)
    iv.classify()

    bp = Blueprint.from_dict(
        blueprint_gen.generate("rect_plate", interview.requirements(iv))
    ).freeze()

    recorded = bp.design_plan["unsupported"]
    assert [u["feature"] for u in recorded] == ["draft_angle"]
    assert recorded[0]["requested"] == 3
    assert bp.verify_hash()


# ---- C: and cannot be removed afterwards ---------------------------------- #
def test_the_unsupported_record_cannot_be_dropped_after_the_freeze():
    from orion import blueprint_gen, interview
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="a plate with a 3 degree draft",
                             family="rect_plate")
    iv.slots = {"length": 120, "width": 80, "thickness": 10}
    iv.unsupported = list(UNSUPPORTED_DRAFT)
    iv.classify()
    bp = Blueprint.from_dict(
        blueprint_gen.generate("rect_plate", interview.requirements(iv))
    ).freeze()

    tampered = copy.deepcopy(bp.to_dict())
    tampered["design_plan"].pop("unsupported")
    assert not Blueprint.from_dict(tampered).verify_hash()


# ---- B: otherwise perfect geometry still cannot be VERIFIED --------------- #
def test_an_unsupported_feature_prevents_verified_on_perfect_geometry():
    """Extents pass, solid valid, volume passes, ledger clean — and one thing
    the user asked for is not in the part and never could be."""
    plan = {"provenance": CLEAN_LEDGER, "unsupported": list(UNSUPPORTED_DRAFT)}
    report = verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1, "watertight": True},
        design_plan=plan,
        topology=CORRECT,
    )
    assert report["verdict"] == verify.UNSOURCED
    # Not a refusal: the geometry is not wrong, the capability is missing.
    assert report["failed"] == []
    row = next(c for c in report["checks"] if c["id"] == "unsupported:draft_angle")
    assert row["status"] == verify.WARN
    assert row["evidence"]["reason"] == "unsupported"
    assert row["evidence"]["requested"] == 3


def test_unsupported_is_distinguishable_from_no_request_at_all():
    """The whole point. Same geometry, same ledger, different claim."""
    clean = verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1},
        design_plan={"provenance": CLEAN_LEDGER},
        topology=CORRECT,
    )
    asked = verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1},
        design_plan={"provenance": CLEAN_LEDGER,
                     "unsupported": list(UNSUPPORTED_DRAFT)},
        topology=CORRECT,
    )
    assert clean["verdict"] == verify.VERIFIED
    assert asked["verdict"] == verify.UNSOURCED
    assert not any(c["id"].startswith("unsupported:") for c in clean["checks"])


def test_unsupported_is_distinguishable_from_omitted():
    """An omission refuses; an unsupported capability warns. Different facts,
    different verdicts, and neither is silence."""
    omitted = _report(BLANK, obligations=O.to_dicts(_obligation()))
    unsupported = verify.from_assertion_rows(
        PASSING_ROWS,
        measured={"valid": True, "solids": 1},
        design_plan={"provenance": CLEAN_LEDGER,
                     "unsupported": list(UNSUPPORTED_DRAFT)},
        topology=CORRECT,
    )
    assert omitted["verdict"] == verify.REFUSED
    assert unsupported["verdict"] == verify.UNSOURCED


def test_no_obligation_is_invented_for_an_unsupported_feature():
    """It has no builder and no observer; manufacturing either would be worse
    than saying so."""
    from orion import obligations as OB

    assert OB.derive("rect_plate", {"draft_angle": 3, "shell": 2}) == []


# ---- D: supported semantics unchanged ------------------------------------- #
@pytest.mark.parametrize(
    "kind,obligations,topology,expected_status",
    [
        ("hole_pattern", _obligation(), CORRECT, "pass"),
        ("hole_pattern", _obligation(), BLANK, "fail"),
        ("bore", [O.Obligation(id="central_bore", kind=O.BORE, label="central bore",
                               count=1, radius=HOLE_R,
                               placement={"form": O.CENTRED},
                               source=("bore_r",))],
         _dressed(HOLE_R, [(0, 0, 0)]), "pass"),
        ("round", _round_obligation(), CORNERS_8, "pass"),
        ("round", _round_obligation(), NO_CORNERS, "fail"),
        ("chamfer", _dressing_obligation(), CHAMFERED, "warn"),
        ("chamfer", _dressing_obligation(), UNCHAMFERED, "fail"),
    ],
)
def test_supported_feature_semantics_are_unchanged(
    kind, obligations, topology, expected_status
):
    assert F.check(obligations, topology)[0]["status"] == expected_status, kind


def test_pocket_and_slot_semantics_are_unchanged():
    pocket = [O.Obligation(id="pocket", kind=O.POCKET, label="pocket",
                           source=("pocket_l",),
                           expect_feature=("Pocket", "Groove"))]
    with_pocket = _with_features(
        CORRECT, {"pocket": {"type": "PartDesign::Pocket", "label": "pocket",
                             "build_index": 1, "faces": ["#o1.s1.f40"],
                             "edges": [], "vertices": []}})
    assert F.check(pocket, with_pocket)[0]["status"] == "warn"
    assert F.check(pocket, CORRECT)[0]["status"] == "fail"
