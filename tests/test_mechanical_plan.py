"""The engineering review that runs between the Blueprint and FreeCAD.

Nothing used to sit there. ``resolve()`` substituted expressions into a graph
and handed it to the kernel, so a part with two holes drilled through the same
material got as far as OCC before anyone noticed.

What these tests pin down is less "does it find things" than **does it find only
real things**. An advisory shown at an approval gate is read by a person, and a
checker that cries wolf is one a person learns to click past — at which point it
is worse than absent, because it also cost their attention.

The nested-circle case is the sharpest example. Two circles whose distance is
less than the sum of their radii *look* like a clash, and on a washer they are
an ordinary bore inside an outer boundary.
"""

import pytest

from app.services import mechanical_plan as mp


def blueprint(variables, sketch_args, builder="rect_with_holes", extra=None):
    """A Blueprint that freezes, so the review sees real resolved geometry."""
    from orion.blueprint import Blueprint

    payload = {
        "part_class": "plate",
        "variables": variables,
        "datums": {},
        "design_plan": {},
        "assertions": [
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": "w*w*t",
            }
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad", "parameters": {"Length": "t"}},
            ]
            + (extra or []),
            "sketches": [
                {"id": "s0", "plane": "XY", "profile": {"builder": builder, "args": sketch_args}}
            ],
            "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"}],
        },
    }
    return Blueprint.from_dict(payload).freeze()


def rules(report) -> list[tuple[str, str]]:
    return [(f["rule"], f["severity"]) for f in report["findings"]]


# --------------------------------------------------------------------------- #
# things that genuinely cannot be built
# --------------------------------------------------------------------------- #
def test_two_holes_through_the_same_material_are_blocking():
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "hr": 5.0, "dx": 2.0},
            {"w": "w", "h": "w", "holes": [("0-dx", "0*w", "hr"), ("dx", "0*w", "hr")]},
        )
    )

    assert rules(report) == [("hole_overlap", "blocking")]
    assert report["blocking"] == 1
    # The numbers are the point: "check hole spacing" is noise a person skips.
    assert "overlap by 6 mm" in report["findings"][0]["message"]


def test_a_dimension_that_resolves_to_zero_is_blocking():
    """Survives the static check, which only rejects literals.

    A perfectly well-formed expression over the named variables can still
    evaluate to zero for the values the model chose, and nothing gets built.
    """
    graph = {
        "features": [
            {"id": "pad", "label": "Pad", "type": "Pad", "parameters": {"Length": 0.0}}
        ],
        "sketches": [],
    }

    report = mp.review(graph)

    assert rules(report) == [("positive_dimension", "blocking")]
    assert "resolves to 0 mm" in report["findings"][0]["message"]


def test_a_fillet_bigger_than_the_face_is_blocking():
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "fr": 20.0},
            {"w": "w", "h": "w"},
            builder="rect",
            extra=[
                {
                    "id": "fil",
                    "type": "Fillet",
                    "parameters": {"Radius": "fr", "_Edges": "all"},
                }
            ],
        )
    )

    assert rules(report) == [("dressup_too_large", "blocking")]


# --------------------------------------------------------------------------- #
# things that must NOT be reported
# --------------------------------------------------------------------------- #
def test_a_bore_inside_an_outer_boundary_is_not_a_clash():
    """A washer is two concentric circles, and it is completely normal.

    Distance-less-than-the-sum-of-radii is true for every annulus in the corpus.
    Flagging on that alone would put a blocking finding on the most common part
    shape there is.
    """
    report = mp.review_blueprint(
        blueprint({"t": 6.0, "w": 40.0}, {"r_outer": "w/2", "r_inner": "w/6"}, builder="annulus")
    )

    assert report["findings"] == []


def test_a_bolt_circle_is_not_a_pile_of_clashes():
    """Holes nested inside an outer circle, which is the normal case."""
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "rbc": 13.0, "rh": 2.0},
            {"n": 6, "r_bc": "rbc", "r_hole": "rh"},
            builder="bolt_circle",
        )
    )

    assert [r for r, s in rules(report) if s == "blocking"] == []


def test_a_well_spaced_plate_is_clean():
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 60.0, "hr": 3.0, "dx": 15.0},
            {"w": "w", "h": "w", "holes": [("0-dx", "0*w", "hr"), ("dx", "0*w", "hr")]},
        )
    )

    assert report["findings"] == []


def test_a_modest_fillet_is_not_flagged():
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "fr": 3.0},
            {"w": "w", "h": "w"},
            builder="rect",
            extra=[
                {
                    "id": "fil",
                    "type": "Fillet",
                    "parameters": {"Radius": "fr", "_Edges": "all"},
                }
            ],
        )
    )

    assert report["findings"] == []


def test_an_enum_parameter_is_never_read_as_a_dimension():
    """Guessing which parameters are lengths is how a checker invents failures."""
    graph = {
        "features": [
            {
                "id": "pad",
                "type": "Pad",
                "parameters": {"Type": "Length", "Midplane": 0, "Reversed": 0},
            }
        ],
        "sketches": [],
    }

    assert mp.review(graph)["findings"] == []


# --------------------------------------------------------------------------- #
# the rules that keep it usable
# --------------------------------------------------------------------------- #
def test_a_thin_land_is_a_warning_not_a_refusal():
    """A rule of thumb is not a physical impossibility.

    A person may well know the hole is not loaded. Blocking on this would refuse
    correct parts on the strength of a heuristic.
    """
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "hr": 3.0, "dx": 12.0},
            {"w": "w", "h": "w", "holes": [("dx", "0*w", "hr")]},
        )
    )

    assert rules(report) == [("thin_land", "warning")]
    assert report["blocking"] == 0


def test_geometry_it_cannot_read_is_an_error_not_a_clean_bill():
    """The failure this checker must never have.

    The first version read the wrong key for a circle's radius, found no
    circles, and passed every overlapping-hole case in the suite. A checker that
    silently drops what it was meant to check is worse than one that does not
    run, because it reports success.
    """
    graph = {
        "features": [],
        "sketches": [{"id": "s0", "geometry": [{"type": "Circle", "cx": 0, "cy": 0}]}],
    }

    report = mp.review(graph)

    assert report["findings"] == []
    assert "error" in report, "unreadable geometry must be reported, not ignored"


def test_a_broken_review_never_costs_a_build():
    """Advisory means advisory: this stage may not take a part down."""
    report = mp.review({"features": None, "sketches": "not a list"})

    assert report["blocking"] == 0
    assert report["findings"] == []


# --------------------------------------------------------------------------- #
# feeding the repair loop
# --------------------------------------------------------------------------- #
def test_blocking_findings_become_a_diagnosis_with_numbers_in_it():
    report = mp.review_blueprint(
        blueprint(
            {"t": 6.0, "w": 40.0, "hr": 5.0, "dx": 2.0},
            {"w": "w", "h": "w", "holes": [("0-dx", "0*w", "hr"), ("dx", "0*w", "hr")]},
        )
    )

    diagnosis = mp.as_diagnosis(report)

    assert "not buildable as dimensioned" in diagnosis
    assert "overlap by 6 mm" in diagnosis
    assert "resolved sketch coordinates" in diagnosis


def test_warnings_alone_produce_no_diagnosis():
    """Only impossibility earns a repair round. A rule of thumb does not."""
    report = {"findings": [{"severity": "warning", "message": "thin land"}]}

    assert mp.as_diagnosis(report) == ""


@pytest.mark.parametrize("report", [{}, {"findings": []}, {"findings": None}])
def test_an_empty_review_produces_no_diagnosis(report):
    assert mp.as_diagnosis(report) == ""
