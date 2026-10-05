"""Report outputs: PDF, GLB node names, URDF assumptions, stale drawings."""
import json
import warnings

import pymupdf
import pytest

from interface_check.pipeline import run_check
from interface_check.report import write_pdf
from interface_check.synth import build

warnings.filterwarnings("ignore", module="build123d")


def test_glb_nodes_named_by_instance_path(tmp_path):
    import trimesh

    files = build("motor_mount", {}, tmp_path)
    report = run_check(files["step"], glb=tmp_path / "m.glb")
    scene = trimesh.load(tmp_path / "m.glb")
    paths = {i["path"] for i in report.to_dict()["instances"]}
    assert paths <= set(scene.graph.nodes)


def test_pdf_lists_findings(tmp_path):
    files = build("bearing_joint", {"housing_bore": 22.5}, tmp_path)
    report = run_check(files["step"], bom=files["bom"])
    pdf = write_pdf(report, tmp_path / "r.pdf")
    text = "".join(p.get_text() for p in pymupdf.open(str(pdf)))
    assert "BEARING_SEAT" in text and "Assumptions" in text


def test_urdf_findings_carry_assumptions(tmp_path):
    files = build("bearing_joint", {"urdf_arm_mass": 1.2}, tmp_path)
    d = run_check(files["step"], bom=files["bom"], urdf=files["urdf"], urdf_map=files["urdf_map"]).to_dict()
    assert any(f["rule_id"] == "URDF_MASS_DRIFT" for f in d["findings"])
    assert any("zero joint position" in a for a in d["assumptions"])
    arm = d["stats"]["urdf"]["links"]["arm_link"]
    assert arm["urdf_mass_kg"] == pytest.approx(arm["cad_mass_kg"] * 1.2, rel=1e-3)


def test_drawing_of_changed_part_is_stale(tmp_path):
    old = build("motor_mount", {}, tmp_path, "old")
    new = build("motor_mount", {"corner_shift": (0, 1.0)}, tmp_path, "new")
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "TITLE: motor_plate   DWG MP-101   REV B")
    doc.save(str(tmp_path / "MP-101.pdf"))
    d = run_check(new["step"], prev_step=old["step"], drawings=[tmp_path / "MP-101.pdf"]).to_dict()
    stale = [f for f in d["findings"] if f["rule_id"] == "DRAWING_STALE"]
    assert stale and stale[0]["severity"] == "high"
    assert d["stats"]["drawings"][0]["revision"] == "B"
    assert json.dumps(d)          # report is JSON-serialisable end to end
