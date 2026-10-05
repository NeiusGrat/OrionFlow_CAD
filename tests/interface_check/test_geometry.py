"""Features, STEP ingest, fastener and bearing tables."""
import warnings

import numpy as np
import pytest
from build123d import Box, Compound, Cylinder, Location, Pos, export_step

from interface_check.features import extract
from interface_check.ingest_step import read_assembly
from interface_check.rules import bearings, fasteners

warnings.filterwarnings("ignore", module="build123d")


def _plate():
    p = Box(80, 60, 10)
    for x in (-15.5, 15.5):
        for y in (-15.5, 15.5):
            p = p - Pos(x, y, 0) * Cylinder(1.7, 12)
    for k in range(6):
        a = np.radians(60 * k)
        p = p - Pos(25 * np.cos(a), 25 * np.sin(a), 0) * Cylinder(2.25, 12)
    return p


def test_holes_and_patterns():
    f = extract(_plate().wrapped)
    assert sorted(round(h.diameter, 2) for h in f.holes) == [3.4] * 4 + [4.5] * 6
    assert all(abs(h.depth - 10) < 1e-6 for h in f.holes)
    kinds = {p.kind: p for p in f.patterns}
    assert kinds["rect"].a == pytest.approx(31.0) and kinds["rect"].b == pytest.approx(31.0)
    assert kinds["rect"].pcd == pytest.approx(31.0 * np.sqrt(2))
    assert kinds["circle"].pcd == pytest.approx(50.0)
    assert len(f.bosses) == 0


def test_fillet_is_not_a_hole():
    from build123d import Axis, BuildPart, fillet
    with BuildPart() as p:
        Box(40, 40, 10)
        fillet(p.edges().filter_by(Axis.Z), 4)
    assert extract(p.part.wrapped).holes == []


def test_boss_and_inertia_about_com():
    f = extract(Cylinder(5, 20).wrapped)
    assert len(f.holes) == 0 and len(f.bosses) == 1 and f.bosses[0].diameter == pytest.approx(10)
    b = extract(Box(10, 20, 30).wrapped)
    m = 6000.0
    assert np.diag(b.inertia) == pytest.approx([m * (20**2 + 30**2) / 12, m * (10**2 + 30**2) / 12,
                                                m * (10**2 + 20**2) / 12])
    assert np.allclose(b.com, 0, atol=1e-9)


def test_step_units_names_and_shared_parts(tmp_path):
    base = Box(100, 50, 5)
    base.label = "base_plate"
    post = Cylinder(3, 30)
    a, b = post.moved(Location((20, 0, 17.5))), post.moved(Location((-20, 0, 17.5)))
    a.label = b.label = "post"
    asm = Compound(children=[base, a, b])
    asm.label = "robot"
    path = tmp_path / "a.step"
    export_step(asm, str(path).replace("\\", "/"))
    parts, instances, findings = read_assembly(path)
    names = sorted(p.name for p in parts.values())
    assert names == ["base_plate", "post"]
    assert sum(1 for i in instances if parts[i.part_id].name == "post") == 2
    plate = next(p for p in parts.values() if p.name == "base_plate")
    assert plate.signature["bbox"] == [5.0, 50.0, 100.0]          # millimetres
    assert findings == []


def test_flattened_step_is_reported(tmp_path):
    shape = Compound([Box(10, 10, 10).solid(), (Pos(30, 0, 0) * Box(10, 10, 10)).solid()])
    path = tmp_path / "flat.step"
    export_step(shape, str(path).replace("\\", "/"))
    parts, instances, findings = read_assembly(path)
    assert [f.rule_id for f in findings] == ["ASSEMBLY_STRUCTURE_MISSING"]
    assert len(instances) == 2 and len(parts) == 1                 # identical solids, one part


@pytest.mark.parametrize("d,expected", [(4.5, {("M4", "clearance")}), (3.3, {("M4", "tap")}),
                                        (2.5, {("M2.5", "nominal"), ("M3", "tap")}), (7.7, set())])
def test_fastener_classify(d, expected):
    assert fasteners.classify(d) == expected


def test_fastener_compatibility():
    assert fasteners.compatible(4.5, 3.3) is True        # clearance M4 + tap M4
    assert fasteners.compatible(4.5, 2.5) is False       # clearance M4 + tap M3
    assert fasteners.compatible(3.4, 3.4) is True
    assert fasteners.compatible(7.7, 3.3) is None        # unknown size: no claim


@pytest.mark.parametrize("name,des,dims", [("608ZZ", "608", (8, 22, 7)), ("bearing_6202-2RS", "6202", (15, 35, 11)),
                                           ("MR105ZZ", "MR105", (5, 10, 4)), ("6800-2RS", "6800", (10, 19, 5))])
def test_bearing_lookup(name, des, dims):
    hit = bearings.lookup(name)
    assert hit is not None and hit[0] == des and hit[1] == tuple(float(x) for x in dims)


def test_bearing_lookup_ignores_plain_parts():
    assert bearings.lookup("base_plate") is None
