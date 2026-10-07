"""M2: features (holes, through/blind, cylinders, patterns) and typed contacts.

The fixtures are build123d assemblies whose every hole, bore and placement is
known exactly (interface_check.synth); the asserted values are those facts.
"""
from __future__ import annotations

import pytest

from review.ingest import build_graph


@pytest.fixture(scope="module")
def chassis(tmp_path_factory):
    from interface_check.synth import build
    out = build("chassis", {}, tmp_path_factory.mktemp("ch"))
    return build_graph(out["step"], "t")


@pytest.fixture(scope="module")
def joint(tmp_path_factory):
    from interface_check.synth import build
    out = build("bearing_joint", {}, tmp_path_factory.mktemp("bj"))
    return build_graph(out["step"], "t")


def _by_part(g, name, kind):
    pid = next(p.id for p in g.parts if p.name == name)
    return [f for f in g.features if f["part_id"] == pid and f["kind"] == kind]


def test_plate_holes_are_measured_exactly(chassis):
    holes = _by_part(chassis, "chassis_plate", "hole")
    got = sorted((h["diameter"], round(h["center"][0]), round(h["center"][1])) for h in holes)
    want = sorted([(3.4, x, y) for x, y in [(-85, -40), (85, -40), (85, 40), (-85, 40)]]
                  + [(4.2, x, 0) for x in (-72, -48, 48, 72)])
    assert got == want
    assert all(h["through"] is True and h["depth"] == pytest.approx(5.0) for h in holes)


def test_blind_hole_is_not_through(joint):
    # base: 4 x d2.5 drilled z -7..1 through a plate z -6..0 -> through; housing bore d22 from z 5 to the top -> blind
    housing = _by_part(joint, "housing", "hole")
    bore = next(h for h in housing if h["diameter"] == pytest.approx(22.0))
    assert bore["through"] is False
    assert all(h["through"] is True for h in _by_part(joint, "base", "hole"))


def test_cylinders(chassis):
    (boss,) = _by_part(chassis, "standoff_M3x35", "cylinder")
    assert boss["diameter"] == pytest.approx(6.0) and boss["length"] == pytest.approx(35.0)


def test_patterns(chassis):
    pats = {(p["pattern"], p["diameter"]): p for p in _by_part(chassis, "chassis_plate", "pattern")}
    rect = pats[("rect", 3.4)]
    assert rect["count"] == 4 and sorted([rect["a"], rect["b"]]) == pytest.approx([80.0, 170.0])
    assert len(rect["holes"]) == 4
    assert pats[("group", 4.2)]["count"] == 4        # collinear feet holes: a group, not a circle or rectangle
    cover = _by_part(chassis, "cover_plate", "pattern")
    assert [(p["pattern"], p["a"], p["b"]) for p in cover] == [("rect", pytest.approx(80.0), pytest.approx(170.0))]


def _names(g):
    part = {p.id: p.name for p in g.parts}
    return {i.id: part[i.part_id] for i in g.instances}


def test_contact_graph(chassis):
    inst = _names(chassis)
    pairs = sorted(tuple(sorted((inst[c["a"]], inst[c["b"]]))) for c in chassis.contacts)
    assert pairs == sorted([("chassis_plate", "side_bracket")] * 2 + [("chassis_plate", "standoff_M3x35")] * 4
                           + [("cover_plate", "standoff_M3x35")] * 4)
    assert chassis.stats.contacts == 10
    for c in chassis.contacts:
        assert c["min_distance"] == pytest.approx(0.0, abs=1e-4)
        assert "planar" in c["kinds"] and "coaxial-hole" in c["kinds"]
        assert c["point"] is not None and len(c["point"]) == 3
    brackets = [c for c in chassis.contacts if "side_bracket" in (inst[c["a"]], inst[c["b"]])]
    assert all(len(c["coaxial_holes"]) == 2 for c in brackets)     # two bolts per bracket


def test_cylindrical_fits(joint):
    inst = _names(joint)
    fits = {tuple(sorted((inst[c["a"]], inst[c["b"]]))): c for c in joint.contacts if c["type"] == "cylindrical"}
    assert set(fits) == {("608ZZ", "housing"), ("608ZZ", "shaft_8mm"), ("arm_link", "shaft_8mm")}
    seat = fits[("608ZZ", "housing")]["fits"][0]
    assert seat["hole_diameter"] == pytest.approx(22.0) and seat["shaft_diameter"] == pytest.approx(22.0)
    assert seat["clearance"] == pytest.approx(0.0, abs=1e-3)
    assert fits[("608ZZ", "shaft_8mm")]["fits"][0]["shaft_diameter"] == pytest.approx(8.0)


def test_mutated_bore_changes_the_fit(tmp_path):
    from interface_check.synth import build
    out = build("bearing_joint", {"housing_bore": 22.6}, tmp_path)       # 0.6 mm oversize bore
    g = build_graph(out["step"], "t")
    inst = _names(g)
    seat = next(c for c in g.contacts if {inst[c["a"]], inst[c["b"]]} == {"608ZZ", "housing"})
    # the bearing no longer touches the bore wall: the pair still touches on its seat face, and the fit
    # is still recognised, with the measured clearance
    fit = seat["fits"][0]
    assert fit["hole_diameter"] == pytest.approx(22.6) and fit["clearance"] == pytest.approx(0.6, abs=1e-3)
