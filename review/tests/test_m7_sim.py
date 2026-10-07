"""M7: sim fidelity — URDF/MJCF parsing, body mapping, mass/COM/inertia/axis drift, corrected inertials, overrides."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from review.sim import parse_mjcf, parse_urdf, pick_robot, principal, quat_to_mat

T = "t"
H = {"Authorization": f"Bearer {T}"}


# ------------------------------------------------------------------ parsing --

MJCF = """<mujoco model="m"><compiler angle="radian"/>
<worldbody>
  <body name="lt" mocap="true" pos="0 0 1"/>
  <body name="hand_a" pos="0.1 0 0" quat="0.7071068 0 0 0.7071068"><freejoint/>
    <inertial pos="0.01 0 0" mass="0.3" fullinertia="1e-4 2e-4 3e-4 0 0 0"/>
    <body name="jaw_a" pos="0 0.015 0" euler="0 0 0.1">
      <joint name="ja" type="hinge" axis="0 0 -1" range="0.03 0.8"/>
      <inertial pos="0.015 0 0" mass="0.1" diaginertia="1e-5 8e-5 9e-5"/>
    </body>
  </body>
  <body name="hand_b" pos="-0.1 0 0"><freejoint/>
    <inertial pos="0 0 0" mass="0.3" diaginertia="1e-4 1e-4 1e-4"/>
    <body name="jaw_b"><joint name="jb" type="hinge" axis="0 0 1"/><inertial pos="0 0 0" mass="0.1" diaginertia="1e-5 1e-5 1e-5"/></body>
  </body>
</worldbody></mujoco>"""


def test_parse_mjcf_poses_and_inertials():
    m = parse_mjcf(MJCF)
    by = {b["name"]: b for b in m["bodies"]}
    Tw = np.asarray(by["jaw_a"]["T_world"])
    # hand_a is rotated 90 deg about z, so the jaw's +y offset becomes -x in the world
    assert Tw[:3, 3] == pytest.approx([0.1 - 0.015, 0, 0], abs=1e-6)
    assert by["hand_a"]["inertial"]["inertia"][1][1] == pytest.approx(2e-4)
    assert principal(by["jaw_a"]["inertial"]["inertia"]) == pytest.approx([1e-5, 8e-5, 9e-5])
    (ja,) = [j for j in m["joints"] if j["name"] == "ja"]
    assert ja["range"] == [0.03, 0.8] and ja["axis"] == [0, 0, -1]


def test_pick_robot_takes_one_copy_of_a_two_hand_scene():
    r = pick_robot(parse_mjcf(MJCF))
    assert r["root"] == "hand_a" and r["copies"] == 2
    assert [b["name"] for b in r["bodies"]] == ["hand_a", "jaw_a"]
    assert [j["name"] for j in r["joints"]] == ["ja"]


def test_parse_urdf_degrees_free():
    u = parse_urdf("""<robot name="r"><link name="a"><inertial><origin xyz="0 0 0.01"/><mass value="2"/>
      <inertia ixx="1" iyy="2" izz="3" ixy="0" ixz="0" iyz="0"/></inertial></link>
      <link name="b"/><joint name="j" type="revolute"><parent link="a"/><child link="b"/>
      <origin xyz="0 0 0.1" rpy="0 0 1.5707963"/><axis xyz="1 0 0"/><limit lower="-1" upper="1"/></joint></robot>""")
    b = next(x for x in u["bodies"] if x["name"] == "b")
    assert np.asarray(b["T_world"])[:3, 3] == pytest.approx([0, 0, 0.1])
    assert np.asarray(b["T_world"])[:3, :3] @ [1, 0, 0] == pytest.approx([0, 1, 0], abs=1e-6)
    assert u["joints"][0]["range"] == [-1, 1]


def test_quat_identity():
    assert quat_to_mat([1, 0, 0, 0]) == pytest.approx(np.eye(3))


# ------------------------------------------------------------- end to end --

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/r.sqlite")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("REVIEW_DEV_TOKEN", T)
    monkeypatch.setenv("REVIEW_INLINE", "1")
    monkeypatch.setenv("REVIEW_AI", "off")
    import review.api as api
    monkeypatch.setattr(api, "_store", None)
    saved = dict(api.app.dependency_overrides)
    api.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(saved)


REG = json.dumps({"cad_origin_mm": [0, 0, 0], "cad_to_canonical_rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                  "cad_to_canonical_scale": 0.001}).encode()


def _run(client, tmp_path, params, name="bj"):
    from interface_check.synth import build
    out = build("bearing_joint", params, tmp_path / name)
    p = client.post("/api/projects", json={"name": name}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"}, files=[
        ("files", ("bj.step", out["step"].read_bytes())), ("files", ("bom.csv", out["bom"].read_bytes())),
        ("files", ("robot.urdf", out["urdf"].read_bytes())), ("files", ("registration.json", REG))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert job["state"] == "done", job
    sim = client.get(f"/api/revisions/{rev['id']}/sim", headers=H).json()
    graph = client.get(f"/api/revisions/{rev['id']}/graph", headers=H).json()
    names = {i["id"]: next(pp["name"] for pp in graph["parts"] if pp["id"] == i["part_id"]) for i in graph["instances"]}
    links = {"base_link": ["base", "housing", "608ZZ"], "arm_link": ["shaft_8mm", "arm_link"]}
    for body, parts in links.items():
        ids = [i for i, n in names.items() if n in parts]
        sim = client.put(f"/api/revisions/{rev['id']}/sim/links", headers=H, json={"body": body, "instances": ids}).json()
    f = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()
    return rev, sim, [x for x in f["findings"] if x["domain"] == "sim"], f["check_runs"]


def test_clean_urdf_matches_except_its_placeholder_inertia(client, tmp_path):
    rev, sim, found, runs = _run(client, tmp_path, {})
    bodies = {b["body"]: b for b in sim["sim"]["analysis"]["bodies"]}
    assert set(bodies) == {"base_link", "arm_link"} and all(b["method"] == "human" for b in bodies.values())
    assert bodies["arm_link"]["cad"]["mass"] == pytest.approx(bodies["arm_link"]["sim"]["mass"], rel=1e-3)
    # the generator writes 1e-4 placeholders for inertia, and the check says so; nothing else fires
    assert {f["check_id"] for f in found} == {"SIM-INERTIA"}
    assert "mjcf" in bodies["arm_link"]["corrected"] and "<inertia ixx=" in bodies["arm_link"]["corrected"]["urdf"]
    assert next(r for r in runs if r["check_id"] == "SIM-AXIS")["status"] == "passed"


@pytest.mark.parametrize("params,check,measure", [
    ({"urdf_arm_mass": 1.10}, "SIM-MASS", None),
    ({"urdf_arm_com_dx": 5.0}, "SIM-COM", None),
    ({"urdf_axis_tilt_deg": 2.0}, "SIM-AXIS", 2.0),
    ({"urdf_joint_dx": 0.003}, "SIM-AXIS", None),
])
def test_seeded_urdf_errors(client, tmp_path, params, check, measure):
    _, _, found, _ = _run(client, tmp_path, params, name=check.lower())
    hits = [f for f in found if f["check_id"] == check]
    assert hits, [(f["check_id"], f["statement"]) for f in found]
    if measure is not None:
        assert hits[0]["measured"]["value"] == pytest.approx(measure, abs=0.05)


def test_no_registration_means_frame_checks_do_not_judge(client, tmp_path):
    from interface_check.synth import build
    out = build("bearing_joint", {"urdf_arm_com_dx": 5.0}, tmp_path / "noreg")
    p = client.post("/api/projects", json={"name": "noreg"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"}, files=[
        ("files", ("bj.step", out["step"].read_bytes())), ("files", ("robot.urdf", out["urdf"].read_bytes()))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert "no registration" in next(s for s in job["steps"] if s["key"] == "sim")["note"]
    f = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()
    assert not [x for x in f["findings"] if x["check_id"] in ("SIM-COM", "SIM-AXIS")]


def test_overrides_need_a_source_and_complete_the_mass(client, tmp_path):
    rev, sim, found, _ = _run(client, tmp_path, {}, name="ov")
    pid = rev["project_id"]
    assert client.put(f"/api/projects/{pid}/overrides", headers=H,
                      json={"part_name": "arm_link", "mass_kg": 0.05}).status_code == 422          # no source
    assert client.put(f"/api/projects/{pid}/overrides", headers=H,
                      json={"part_name": "arm_link", "source": "datasheet p.3"}).status_code == 422  # nothing set
    ov = client.put(f"/api/projects/{pid}/overrides", headers=H,
                    json={"part_name": "arm_link", "mass_kg": 0.5, "source": "weighed on the bench"}).json()
    assert ov[0]["mass_kg"] == 0.5
    sim = client.get(f"/api/revisions/{rev['id']}/sim", headers=H).json()
    arm = next(p for p in sim["parts"] if p["name"] == "arm_link")
    assert arm["mass"] == 0.5 and "weighed on the bench" in arm["mass_source"]
    f = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()["findings"]
    assert any(x["check_id"] == "SIM-MASS" for x in f)                  # the stated mass no longer matches the URDF
    client.request("DELETE", f"/api/projects/{pid}/overrides", headers=H, json={"part_name": "arm_link"})
    f = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()["findings"]
    assert not any(x["check_id"] == "SIM-MASS" for x in f)
