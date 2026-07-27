"""The up-cut bug, pinned against the real kernel.

Everything else in ``orion/tests`` is pure Python; this module builds geometry,
so it is marked ``slow`` and skips when FreeCAD is absent.

The defect: a subtractive attachment cut 1 mm *upward* out of its mount plane
as well as downward through the land. Over an exposed land that millimetre
removes air and the closed form stays exact. Where another feature rises off the
same plane it removes ``overlap_area * 1 mm`` of that feature — material the
``delta`` expression never accounted for. The resulting error is 1e-5..4e-4
relative: far too small to look like a modelling mistake, far too large to be
floating point, which is exactly why it survived a 25,000-part corpus.

The case below is taken from a real generation that failed verification: a
pillow block whose vent slot spans x 30.5..40.5 while the housing ends at 35.
"""

import math
import os
import tempfile

import pytest

from orion import forge
from orion.blueprint import Blueprint

pytestmark = pytest.mark.slow


def _freecad_missing() -> bool:
    try:
        forge._freecad_python()
    except RuntimeError:
        return True
    return False


requires_freecad = pytest.mark.skipif(
    _freecad_missing(), reason="no FreeCAD python (set ORION_FREECAD_PYTHON)")

VARS = {"L": 106.0, "W": 40.0, "base_t": 15.0, "hous_l": 70.0, "hous_w": 26.0,
        "hous_h": 38.0, "bore_r": 6.5, "att0_cx": 35.5, "att0_cy": 0.0,
        "att0_sl": 6.0, "att0_sr": 2.0}

BODY = ("L*W*base_t + hous_l*hous_w*hous_h - pi*bore_r**2*hous_w"
        " + (-(att0_sl*2*att0_sr + pi*att0_sr**2)*(base_t))")


def _pillow_block(vent_params: dict) -> Blueprint:
    """The part, parameterised only by how the vent pocket is cut."""
    return Blueprint(
        part_class="pillow_block_plus_vent_slot",
        variables=dict(VARS),
        datums={"A": "bottom face z=0"},
        design_plan={"intent": "up-cut regression"},
        assertions=[
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": BODY},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
             "target": "1"},
            {"id": "closed", "kind": "watertight", "tier": 1},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_base", "type": "Sketch", "parameters": {}},
                {"id": "base", "type": "Pad",
                 "parameters": {"Length": "base_t", "Type": "Length"}},
                {"id": "s_hous", "type": "Sketch", "parameters": {}},
                {"id": "housing", "type": "Pad",
                 "parameters": {"Length": "hous_h", "Type": "Length"}},
                {"id": "s_bore", "type": "Sketch", "parameters": {}},
                {"id": "bore", "type": "Pocket",
                 "parameters": {"Length": "W", "Type": "Length",
                                "Length2": "W", "Type2": "Length",
                                "SideType": "Two sides"}},
                {"id": "s_att0_vent", "type": "Sketch", "parameters": {}},
                {"id": "att0_vent", "type": "Pocket",
                 "parameters": vent_params},
            ],
            "sketches": [
                {"id": "s_base", "plane": "XY",
                 "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
                {"id": "s_hous", "plane": "XY", "z": "base_t",
                 "profile": {"builder": "rect",
                             "args": {"w": "hous_l", "h": "hous_w"}}},
                {"id": "s_bore", "plane": "XZ", "z": "0",
                 "profile": {"builder": "circle",
                             "args": {"r": "bore_r", "cx": "0",
                                      "cy": "base_t + hous_h/2"}}},
                {"id": "s_att0_vent", "plane": "XY", "z": "base_t",
                 "profile": {"builder": "slot",
                             "args": {"length": "att0_sl", "r": "att0_sr",
                                      "cx": "att0_cx", "cy": "att0_cy"}}},
            ],
            "dependencies": [
                {"source": "s_base", "target": "base", "kind": "profile"},
                {"source": "base", "target": "housing", "kind": "base"},
                {"source": "s_hous", "target": "housing", "kind": "profile"},
                {"source": "s_bore", "target": "bore", "kind": "profile"},
                {"source": "housing", "target": "bore", "kind": "base"},
                {"source": "s_att0_vent", "target": "att0_vent",
                 "kind": "profile"},
                {"source": "bore", "target": "att0_vent", "kind": "base"},
            ],
        },
    ).freeze()


ONE_SIDED = {"Length": "base_t + 1", "Type": "Length"}
TWO_SIDED = {"Length": "base_t + 1", "Type": "Length", "Length2": "1",
             "Type2": "Length", "SideType": "Two sides"}


def _slot_area_left_of(v: dict, edge: float) -> float:
    """Area of the stadium footprint lying at x < ``edge``.

    Piecewise in the leading cap: nothing left of the cap, a circular segment
    inside it, then the full half-disc plus straight section beyond it.
    """
    sr, sl, cx = v["att0_sr"], v["att0_sl"], v["att0_cx"]
    cap = cx - sl / 2                       # centre of the leading cap
    if edge <= cap - sr:
        return 0.0
    if edge <= cap:                         # segment of the cap only
        d = cap - edge
        return sr * sr * math.acos(d / sr) - d * math.sqrt(sr * sr - d * d)
    straight = min(edge, cx + sl / 2) - cap
    area = math.pi * sr * sr / 2 + straight * 2 * sr
    if edge > cx + sl / 2:                  # into the trailing cap
        d = edge - (cx + sl / 2)
        d = min(d, sr)
        area += math.pi * sr * sr / 2 - (
            sr * sr * math.acos(d / sr) - d * math.sqrt(sr * sr - d * d))
    return area


def _build(bp: Blueprint):
    with tempfile.TemporaryDirectory(prefix="upcut_") as wd:
        _log, measured = forge.build_and_measure(bp.resolve(), wd, "part")
    return measured


def _predicted(bp: Blueprint) -> float:
    return next(a["target_value"] for a in bp.resolve_assertions()
                if a["id"] == "body")


@requires_freecad
def test_one_sided_pocket_predicts_its_own_volume_exactly():
    """The fix: with the up-cut gone the closed form describes the solid even
    though the slot lies under the housing."""
    bp = _pillow_block(ONE_SIDED)
    measured = _build(bp)
    assert measured.get("watertight") is True
    assert measured.get("solids") == 1
    got, want = measured["body_volume"], _predicted(bp)
    assert abs(got - want) / want < 1e-12, \
        f"predicted {want}, kernel measured {got}"


@requires_freecad
def test_two_sided_pocket_is_the_bug_this_guards():
    """The old idiom, kept as evidence. The error must be small enough to have
    been missed and large enough to fail the 1e-6 contract — if this ever comes
    out exact, the regression above has stopped proving anything."""
    bp = _pillow_block(TWO_SIDED)
    measured = _build(bp)
    got, want = measured["body_volume"], _predicted(bp)
    rel = abs(got - want) / want
    assert 1e-6 < rel < 1e-2, f"expected the known mispredict, got rel={rel}"

    # The missing material is exactly the slot footprint lying under the
    # housing, one millimetre deep — computed here from first principles.
    overlap = _slot_area_left_of(VARS, VARS["hous_l"] / 2)
    assert abs((want - got) - overlap * 1.0) < 1e-6, \
        "the shortfall is not the overlap footprint x 1 mm"


@requires_freecad
def test_clear_of_the_housing_both_idioms_agree():
    """Identical geometry where the slot does not reach the housing — the
    property that made the fix safe to apply to every existing part."""
    clear = dict(VARS, att0_cx=46.0)        # slot spans 41..51, housing ends 35
    out = {}
    for label, params in (("one", ONE_SIDED), ("two", TWO_SIDED)):
        bp = _pillow_block(params)
        bp = Blueprint(**{**bp.__dict__, "blueprint_hash": "",
                          "variables": clear}).freeze()
        measured = _build(bp)
        out[label] = (measured["body_volume"], _predicted(bp))
    (g1, w1), (g2, w2) = out["one"], out["two"]
    assert abs(g1 - g2) < 1e-9, "removing the up-cut changed clear geometry"
    for got, want in (out["one"], out["two"]):
        assert abs(got - want) / want < 1e-12
