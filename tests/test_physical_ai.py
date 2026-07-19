"""Tests for the Physical AI harness (orion_physical_ai).

Everything here is offline: no LLM calls (deterministic reasoning fallback),
no sandbox execution (meshes are built directly with trimesh).
"""

import xml.etree.ElementTree as ET

import pytest
import trimesh

from orion_physical_ai import (
    PhysicalAIAgent,
    analyze_part,
    classify_intent,
    design_reasoning,
    generate_sdf,
    generate_urdf,
    get_knowledge_base,
    mass_properties,
    plan_to_brief,
    source_parts,
)

KB = get_knowledge_base()


# ── knowledge base ───────────────────────────────────────────────


def test_kb_clearance_and_tap_lookups():
    assert KB.clearance_hole("M3") == 3.4
    assert KB.clearance_hole("M3", fit="close") == 3.2
    assert KB.tap_drill("M5") == 4.2


def test_kb_nema_table():
    nema17 = KB.nema("NEMA17")
    assert nema17["face_mm"] == 42.3
    assert nema17["pcd_mm"] == 31.0
    assert nema17["mount_thread"] == "M3"


def test_kb_unknown_material_lists_options():
    with pytest.raises(KeyError, match="aluminum_6061_t6"):
        KB.material("unobtainium")


def test_kb_nearest_standard_drill():
    assert KB.nearest_standard_drill(3.37) == 3.4
    assert KB.nearest_standard_drill(6.75) == 6.8


# ── sourcing ─────────────────────────────────────────────────────


def test_source_parts_nema17_and_fasteners():
    hits = source_parts(
        "A motor mounting bracket for a NEMA 17 stepper with 4x M3 clearance holes"
    )
    ids = {h["part_id"] for h in hits}
    assert "nema17_stepper" in ids
    assert "m3_shcs" in ids
    nema = next(h for h in hits if h["part_id"] == "nema17_stepper")
    assert nema["spec"]["mount_hole_pcd_mm"] == 31.0


def test_source_parts_bearing_extrusion_pi():
    hits = source_parts(
        "2020 aluminum extrusion bracket holding a 608ZZ bearing and a Raspberry Pi"
    )
    ids = {h["part_id"] for h in hits}
    assert {"extrusion_2020", "608zz_bearing", "raspberry_pi_4b"} <= ids


def test_source_parts_no_false_positives_on_plain_prompt():
    assert source_parts("Rectangular plate 100 x 60 x 5 mm") == []


# ── reasoning (deterministic fallback) ───────────────────────────


def test_fallback_plan_grounds_motor_mount():
    prompt = "NEMA 17 mount plate 50 x 50 x 6 mm with M3 holes"
    parts = source_parts(prompt)
    plan = design_reasoning(prompt, parts, KB, llm=None)
    assert plan["reasoning_mode"] == "deterministic_fallback"
    assert plan["envelope_mm"] == [50, 50, 6]
    pattern = next(f for f in plan["features"] if f["type"] == "pattern")
    assert pattern["dims_mm"]["pcd"] == 31.0
    assert pattern["dims_mm"]["hole_dia"] == 3.4  # clearance, not nominal 3.0


def test_knowledge_context_pulls_material_heuristics_fits_dfm():
    from orion_physical_ai import knowledge_context

    prompt = "A strong bearing bracket for a 608ZZ bearing, CNC machined"
    parts = source_parts(prompt)
    lines, process = knowledge_context(prompt, parts, "aluminum_6061_t6", KB)
    joined = "\n".join(lines)
    assert process == "cnc_milling"
    assert "608ZZ" in joined  # sourced part facts
    assert "density 2.7" in joined  # material properties
    assert "Design rule [mounting_bracket]" in joined  # bracket heuristics
    assert "Design rule [bearing_seat]" in joined  # bearing fits heuristics
    assert "Fit [" in joined  # ISO 286 fits
    assert "DFM [cnc_milling]" in joined  # process rules
    assert '"strong" requested' in joined  # strength keyword rule


def test_fallback_plan_records_knowledge_used():
    prompt = "NEMA 17 bracket with M3 holes"
    parts = source_parts(prompt)
    plan = design_reasoning(prompt, parts, KB, llm=None)
    assert plan["knowledge_used"], "plan must record the knowledge it applied"
    assert any("NEMA 17" in k for k in plan["knowledge_used"])


def test_plan_to_brief_injects_constraints():
    prompt = "NEMA 17 bracket"
    parts = source_parts(prompt)
    plan = design_reasoning(prompt, parts, KB, llm=None)
    brief = plan_to_brief(prompt, plan, parts, KB)
    assert "ENGINEERING CONSTRAINTS" in brief
    assert "31.0" in brief  # the PCD fact made it into the brief


def test_intent_classification():
    assert classify_intent("make it 2mm thicker") == "edit"
    assert classify_intent("export a URDF for gazebo") == "simulate"
    assert classify_intent("a flange with six holes") == "generate"


# ── simulation export (analytic ground truth) ────────────────────


@pytest.fixture
def box_stl(tmp_path):
    """100 x 50 x 10 mm box; analytic mass/inertia are exact."""
    mesh = trimesh.creation.box(extents=[100, 50, 10])
    path = tmp_path / "box.stl"
    mesh.export(path)
    return str(path)


def test_mass_properties_match_analytic_box(box_stl):
    props = mass_properties(box_stl, density_g_cm3=2.70)
    assert props["mass_kg"] == pytest.approx(0.135, rel=1e-3)
    assert props["volume_mm3"] == pytest.approx(50_000, rel=1e-6)
    # Ixx about COM for a 0.1 x 0.05 x 0.01 m box: m/12 * (b^2 + c^2)
    assert props["inertia_kg_m2"]["ixx"] == pytest.approx(
        0.135 / 12 * (0.05**2 + 0.01**2), rel=1e-3
    )
    assert props["inertia_kg_m2"]["ixy"] == pytest.approx(0.0, abs=1e-9)


def test_urdf_is_valid_xml_with_inertia(box_stl):
    props = mass_properties(box_stl, density_g_cm3=2.70)
    urdf = generate_urdf("test_part", "box.stl", "box.stl", props)
    root = ET.fromstring(urdf)
    assert root.tag == "robot"
    mass = root.find(".//inertial/mass")
    assert float(mass.get("value")) == pytest.approx(0.135, rel=1e-3)
    mesh = root.find(".//visual/geometry/mesh")
    assert mesh.get("scale") == "0.001 0.001 0.001"  # mm meshes -> metres


def test_urdf_renders_plan_joints(box_stl):
    props = mass_properties(box_stl, density_g_cm3=2.70)
    urdf = generate_urdf(
        "gimbal", "box.stl", "box.stl", props,
        joints=[{"name": "pan", "type": "revolute", "axis": [0, 0, 1], "limit_deg": [-90, 90]}],
    )
    root = ET.fromstring(urdf)
    joint = root.find(".//joint")
    assert joint.get("type") == "revolute"
    assert joint.find("limit") is not None


def test_sdf_is_valid_xml(box_stl):
    props = mass_properties(box_stl, density_g_cm3=2.70)
    sdf = generate_sdf("test_part", "box.stl", "box.stl", props)
    root = ET.fromstring(sdf)
    assert root.tag == "sdf" and root.get("version") == "1.7"
    assert float(root.find(".//inertial/mass").text) == pytest.approx(0.135, rel=1e-3)


# ── analysis ─────────────────────────────────────────────────────


def test_analyze_clean_box_scores_100(box_stl):
    report = analyze_part(box_stl, "aluminum_6061_t6", KB)
    assert report["manufacturability_score"] == 100
    assert report["properties"]["watertight"] is True
    assert report["properties"]["mass_g"] == pytest.approx(135.0, rel=1e-3)
    assert report["process"] == "cnc_milling"


def test_analyze_flags_below_min_wall(tmp_path):
    mesh = trimesh.creation.box(extents=[50, 50, 0.5])  # 0.5 mm "foil"
    path = tmp_path / "thin.stl"
    mesh.export(path)
    report = analyze_part(str(path), "aluminum_6061_t6", KB)
    assert any(i["severity"] == "critical" for i in report["issues"])
    assert report["manufacturability_score"] < 100


# ── agent orchestration (stubbed generation service) ─────────────


class _StubFiles:
    def __init__(self):
        self.step = None
        self.stl = None
        self.glb = None

    def model_dump(self):
        return {"step": self.step, "stl": self.stl, "glb": self.glb}


class _StubResponse:
    def __init__(self, success):
        self.success = success
        self.ofl_code = "# code"
        self.files = _StubFiles()
        self.parameters = []
        self.stats = None
        self.repair_attempts = 1
        self.error = None if success else "boom"


class _StubService:
    class llm:  # noqa: N801 - mimics OFLLLMClient attribute
        @staticmethod
        def _chat(messages):
            raise RuntimeError("offline")

    def __init__(self, success=True):
        self._success = success

    def generate_from_prompt(self, prompt, max_repairs=2):
        self.last_prompt = prompt
        return _StubResponse(self._success)


def test_agent_bundle_shape_and_grounded_brief():
    service = _StubService(success=True)
    agent = PhysicalAIAgent(generation_service=service, use_llm_reasoning=False)
    bundle = agent.design("NEMA 17 bracket with M3 holes")
    assert bundle["success"] is True
    assert bundle["intent"] == "generate"
    assert any(p["part_id"] == "nema17_stepper" for p in bundle["sourced_parts"])
    # the grounded brief (with catalog facts) is what reached the generator
    assert "ENGINEERING CONSTRAINTS" in service.last_prompt
    phases = [t["phase"] for t in bundle["trace"]]
    assert phases[:3] == ["intent", "source", "reason"]


def test_agent_failure_propagates():
    agent = PhysicalAIAgent(generation_service=_StubService(success=False), use_llm_reasoning=False)
    bundle = agent.design("a plate")
    assert bundle["success"] is False
    assert bundle["error"] == "boom"
    assert bundle["urdf"] is None


# ── endpoint ─────────────────────────────────────────────────────


def test_agent_endpoint_smoke(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import agent as agent_mod

    stub = PhysicalAIAgent(generation_service=_StubService(True), use_llm_reasoning=False)
    monkeypatch.setattr(agent_mod, "_agent", stub)

    app = FastAPI()
    app.include_router(agent_mod.router, prefix="/api/v1/agent")
    client = TestClient(app)

    resp = client.post(
        "/api/v1/agent/design",
        json={"prompt": "NEMA 17 bracket", "use_llm_reasoning": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["sourced_parts"][0]["part_id"] == "nema17_stepper"
    assert isinstance(body["trace"], list) and body["trace"]
