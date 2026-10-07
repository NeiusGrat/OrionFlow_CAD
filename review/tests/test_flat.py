"""Flattened STEP files: copies merged into one part must be placed where their geometry is."""
from __future__ import annotations

import numpy as np
import pytest

from review.ingest import build_graph


def _flat_step(path, solids):
    """One shape holding many solids, no assembly tree: a 'save as one body' export.

    Written through XCAF with the compound registered as a single (non-assembly) shape, with every
    placement baked into the geometry: that is what a flattened CAD export contains.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Compound
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    comp, b = TopoDS_Compound(), BRep_Builder()
    b.MakeCompound(comp)
    for s in solids:
        loc = s.wrapped.Location()
        b.Add(comp, BRepBuilderAPI_Transform(s.wrapped.Located(TopLoc_Location()), loc.Transformation(), True).Shape())
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    tool.AddShape(comp, False)                     # makeAssembly = False: one shape, not a tree
    w = STEPCAFControl_Writer()
    w.Transfer(doc, STEPControl_AsIs)
    assert w.Write(str(path)) == IFSelect_RetDone
    return path


@pytest.fixture(scope="module")
def flat(tmp_path_factory):
    from build123d import Box, Cylinder, Location, Pos, Rot

    # an asymmetric bracket placed three ways, a bolt-like cylinder twice, and a plate
    bracket = Box(30, 12, 6) + Pos(12, 0, 8) * Box(6, 12, 10)
    placements = [Location((0, 0, 0)), Location((80, 10, 0), (0, 0, 90)), Location((0, 70, 15), (30, 0, 45))]
    brackets = [bracket.moved(L) for L in placements]
    bolt = Cylinder(1.5, 10) + Pos(0, 0, 5.5) * Cylinder(2.7, 1)
    bolts = [bolt.moved(Location((40, 40, 0))), bolt.moved(Location((-30, 20, 5), (90, 0, 0)))]
    plate = Pos(0, 0, -20) * Box(200, 160, 4)
    shapes = brackets + bolts + [plate]
    path = _flat_step(tmp_path_factory.mktemp("flat") / "flat.step", shapes)
    coms = [np.array([s.center().X, s.center().Y, s.center().Z]) for s in shapes]
    return path, coms


def test_copies_are_placed_by_their_geometry(flat):
    path, coms = flat
    g = build_graph(path, "t")
    assert g.stats.flat and g.stats.instances == 6
    assert g.stats.parts == 3                          # bracket, bolt, plate: copies folded into their part
    assert any(n.startswith("FLAT_PLACEMENTS_RECOVERED: 3 copies") for n in g.ingest_notes)
    world = []
    for i in g.instances:
        T = np.asarray(i.transform)
        c = np.asarray(g.part(i.part_id).com)
        world.append(T[:3, :3] @ c + T[:3, 3])
    # every real solid's centre of mass is matched by exactly one placed instance
    for c in coms:
        d = [float(np.linalg.norm(w - c)) for w in world]
        assert min(d) < 1e-3, (c, sorted(d)[:2])


def test_no_false_duplicates_in_a_flat_file(flat):
    from review.checks import run_checks
    path, _ = flat
    findings, _ = run_checks(build_graph(path, "t", analyse=False))
    structure = [f for f in findings if f.domain == "structure"]
    assert [f.check_id for f in structure] == ["ST-TREE"]         # only the missing tree, no false duplicates
    findings = structure
    assert findings[0].title == "No assembly structure in the file"


def test_mirror_copy_is_its_own_part_and_labelled(tmp_path):
    from build123d import Box, Location, Plane, Pos, mirror

    asym = Box(30, 12, 6) + Pos(12, 4, 8) * Box(6, 4, 10)
    left = asym.moved(Location((0, 0, 0)))
    right = mirror(asym, Plane.YZ).moved(Location((100, 0, 0)))
    path = _flat_step(tmp_path / "lr.step", [left, right, Pos(0, 0, -20) * Box(200, 60, 4)])
    g = build_graph(path, "t", analyse=False)
    assert g.stats.parts == 3
    assert any("mirror images" in n for n in g.ingest_notes)
    assert any(p.name.endswith("_mirror") for p in g.parts)
