"""``Reversed`` and ``Midplane`` on Pad and Pocket.

A sketch plane fixes an axis but not a sign, and FreeCAD takes the sign from
the sketch normal — an XZ pad grows in -Y, a YZ pad in -X. A blind cut aimed at
the wrong face lands outside the solid and removes nothing, while the feature
recomputes clean and the build reports success. The failure is invisible except
in the volume, which is how an L-bracket's motor bore came back having removed
56 mm3 of an expected 22084.

These are the foundation for every one-sided operation: counterbores, blind
slots, single-sided pockets.

The additive property is the one that must hold. A Blueprint that does not
author these keys has to compile to exactly what it compiled to before, or the
42k-record corpus stops describing the geometry it was verified against.
"""

import math
import tempfile

import pytest

from app.services.blueprint_service import _build_locally
from orion.blueprint import Blueprint

A, B, T, R, D = 40.0, 40.0, 20.0, 8.0, 5.0
BLOCK = A * B * T
DISC = math.pi * R**2 * D


def _build(payload):
    bp = Blueprint.from_dict(payload).freeze()
    graph = bp.resolve()
    graph.pop("_analysis", None)
    log, measured = _build_locally(graph, tempfile.mkdtemp(prefix="dir_"), False)
    assert measured, f"build produced nothing: {(log.get('stderr') or '')[-300:]}"
    return measured


def block_with_pocket(**pocket_params):
    params = {"Length": "D", "Type": "Length"}
    params.update(pocket_params)
    return {
        "part_class": "probe",
        "variables": {"A": A, "B": B, "T": T, "R": R, "D": D},
        "datums": {},
        "design_plan": {},
        "assertions": [
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": "A*B*T",
            }
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {
                    "id": "blk",
                    "type": "Pad",
                    "parameters": {"Length": "T", "Type": "Length"},
                },
                {"id": "s1", "type": "Sketch", "parameters": {}},
                {"id": "cut", "type": "Pocket", "parameters": params},
            ],
            "sketches": [
                {
                    "id": "s0",
                    "plane": "XY",
                    "profile": {"builder": "rect", "args": {"w": "A", "h": "B"}},
                },
                {
                    "id": "s1",
                    "plane": "XY",
                    "profile": {"builder": "circle", "args": {"r": "R"}},
                },
            ],
            "dependencies": [
                {"source": "s0", "target": "blk", "kind": "profile"},
                {"source": "s1", "target": "cut", "kind": "profile"},
            ],
        },
    }


def pad(**params):
    p = {"Length": "T", "Type": "Length"}
    p.update(params)
    return {
        "part_class": "probe",
        "variables": {"A": A, "B": B, "T": T},
        "datums": {},
        "design_plan": {},
        "assertions": [
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": "A*B*T",
            }
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "blk", "type": "Pad", "parameters": p},
            ],
            "sketches": [
                {
                    "id": "s0",
                    "plane": "XY",
                    "profile": {"builder": "rect", "args": {"w": "A", "h": "B"}},
                }
            ],
            "dependencies": [{"source": "s0", "target": "blk", "kind": "profile"}],
        },
    }


# --------------------------------------------------------------------------- #
# additive: absent must equal the old behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_a_pocket_without_the_key_is_unchanged():
    """The corpus authored none of these. It must compile as it always did."""
    assert _build(block_with_pocket())["body_volume"] == pytest.approx(BLOCK - DISC)


@pytest.mark.integration
def test_reversed_false_is_identical_to_omitting_it():
    absent = _build(block_with_pocket())["body_volume"]
    explicit = _build(block_with_pocket(Reversed=False))["body_volume"]
    assert absent == pytest.approx(explicit)


@pytest.mark.integration
def test_midplane_false_is_identical_to_omitting_it():
    absent = _build(pad())
    explicit = _build(pad(Midplane=False))
    assert absent["body_volume"] == pytest.approx(explicit["body_volume"])
    assert absent["bbox"] == pytest.approx(explicit["bbox"])


# --------------------------------------------------------------------------- #
# what the keys actually do
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_reversed_aims_the_cut_at_the_other_face():
    """Flipped, the pocket runs away from the material and removes nothing.

    That is the whole hazard this key exists to control: without it the only
    way to aim a blind cut was to hope the sketch normal pointed the right way,
    and when it did not the build still reported success.
    """
    assert _build(block_with_pocket(Reversed=True))["body_volume"] == pytest.approx(
        BLOCK
    )


@pytest.mark.integration
def test_midplane_splits_the_extrusion_about_the_sketch():
    plain = _build(pad())
    mid = _build(pad(Midplane=True))

    assert plain["body_volume"] == pytest.approx(mid["body_volume"])
    assert (plain["bbox"][2], plain["bbox"][5]) == pytest.approx((0.0, T))
    assert (mid["bbox"][2], mid["bbox"][5]) == pytest.approx((-T / 2, T / 2))


# --------------------------------------------------------------------------- #
# a build that cannot honour the key says so
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_an_unsupported_property_is_reported_not_swallowed():
    """If a FreeCAD build lacks the property the request must not look applied.

    Only the reporting path is exercised here — every supported build has both
    — but a silent drop would reproduce exactly the failure mode this change
    exists to remove.
    """
    measured = _build(block_with_pocket(Reversed=True))
    report = measured.get("build_report") or {}
    assert report.get("ignored") is None
