"""M8: joints (sim + coupling), confirmation, and a sweep through the range on exact geometry.

The fixture is the bearing joint (arm on a shaft in a 608 bearing) with two Ø6 posts standing at 40 mm from
the axis, at +60° and -120°. The arm's side faces are 10 mm from its centre line, so the first contact is
analytic: sin(phi - theta) = (10 + 3) / 40, i.e. theta = +41.034° and -101.034°.
"""
from __future__ import annotations

import json
import math

import pytest

from review.motion import couple, poly
from review.sim import parse_mjcf, parse_urdf, pick_robot

T = "t"
H = {"Authorization": f"Bearer {T}"}
HIT_UP = 60 - math.degrees(math.asin(13 / 40))
HIT_DN = -120 + math.degrees(math.asin(13 / 40))


# ---------------------------------------------------------------- couplings --

def test_mjcf_equality_and_urdf_mimic_couple_joints():
    m = pick_robot(parse_mjcf("""<mujoco><worldbody><body name="h"><freejoint/>
      <body name="a"><joint name="ja" axis="0 0 1"/></body><body name="b"><joint name="jb" axis="0 0 1"/></body>
      </body></worldbody><equality><joint name="gear" joint1="jb" joint2="ja" polycoef="0 -1 0 0 0"/></equality></mujoco>"""))
    assert m["couplings"] == [{"joint": "jb", "of": "ja", "coef": [0, -1, 0, 0, 0], "source": '<equality><joint name="gear">'}]
    js = [{"name": "ja"}, {"name": "jb"}]
    couple(js, m["couplings"])
    assert js[0]["followers"][0]["name"] == "jb" and poly(js[0]["followers"][0]["coef"], 0.3) == pytest.approx(-0.3)
    assert js[1]["followers"][0]["name"] == "ja" and poly(js[1]["followers"][0]["coef"], -0.3) == pytest.approx(0.3)
    u = parse_urdf("""<robot name="r"><link name="a"/><link name="b"/><link name="c"/>
      <joint name="j1" type="revolute"><parent link="a"/><child link="b"/><axis xyz="0 0 1"/><limit lower="-1" upper="1"/></joint>
      <joint name="j2" type="revolute"><parent link="a"/><child link="c"/><axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
      <mimic joint="j1" multiplier="2" offset="0.1"/></joint></robot>""")
    assert u["couplings"] == [{"joint": "j2", "of": "j1", "coef": [0.1, 2.0], "source": "<mimic> on joint j2"}]


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


def _fixture(tmp_path):
    from build123d import Compound, Location, export_step

    from interface_check.synth import _label, bearing_joint, bearing_urdf, cyl

    parts, _ = bearing_joint({})
    posts = []
    for k, phi in enumerate((60.0, -120.0)):
        x, y = 40 * math.cos(math.radians(phi)), 40 * math.sin(math.radians(phi))
        posts.append(_label(cyl(0, 0, 6.0, 0, 25).moved(Location((x, y, 0))), "post"))
    step = tmp_path / "arm.step"
    export_step(_label(Compound(children=parts + posts), "arm_with_posts"), str(step).replace("\\", "/"))
    return step.read_bytes(), bearing_urdf(parts, {}).encode()


def _revision(client, tmp_path):
    step, urdf = _fixture(tmp_path)
    p = client.post("/api/projects", json={"name": "arm"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"}, files=[
        ("files", ("arm.step", step)), ("files", ("robot.urdf", urdf)), ("files", ("registration.json", REG))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=H).json()["state"] == "done"
    graph = client.get(f"/api/revisions/{rev['id']}/graph", headers=H).json()
    names = {i["id"]: next(pp["name"] for pp in graph["parts"] if pp["id"] == i["part_id"]) for i in graph["instances"]}
    for body, want in {"base_link": ["base", "housing", "608ZZ", "post"], "arm_link": ["shaft_8mm", "arm_link"]}.items():
        ids = [i for i, n in names.items() if n in want]
        client.put(f"/api/revisions/{rev['id']}/sim/links", headers=H, json={"body": body, "instances": ids})
    return rev["id"], names


def _confirm_and_sweep(client, rid, **over):
    m = client.get(f"/api/revisions/{rid}/motion", headers=H).json()
    (row,) = m["joints"]
    spec = {k: v for k, v in row["candidate"].items() if k not in ("body", "parent", "evidence")} | over
    m = client.put(f"/api/revisions/{rid}/motion/joints", headers=H, json=spec)
    assert m.status_code == 200, m.text
    sw = client.post(f"/api/revisions/{rid}/motion/sweeps", headers=H, json={"key": spec["key"]}).json()
    sw = client.get(f"/api/sweeps/{sw['id']}", headers=H).json()
    assert sw["state"] == "done", sw.get("error")
    f = client.get(f"/api/revisions/{rid}/findings", headers=H).json()
    return row, sw["result"], [x for x in f["findings"] if x["check_id"] == "CM-JOINT-SWEEP"], f["check_runs"]


def test_sweep_finds_both_collisions_at_the_analytic_angles(client, tmp_path):
    rid, names = _revision(client, tmp_path)
    runs = client.get(f"/api/revisions/{rid}/findings", headers=H).json()["check_runs"]
    assert next(r for r in runs if r["check_id"] == "CM-JOINT-SWEEP")["status"] == "not_run"      # nothing swept yet

    row, r, found, runs = _confirm_and_sweep(client, rid)
    cand = row["candidate"]
    assert cand["source"] == "sim" and cand["axis"] == pytest.approx([0, 0, 1], abs=1e-9)
    assert cand["point"][:2] == pytest.approx([0, 0], abs=1e-6)
    assert sorted(names[i] for i in cand["moving"]) == ["arm_link", "shaft_8mm"]
    up, dn = r["collisions"]["upper"], r["collisions"]["lower"]
    assert math.degrees(up["q"]) == pytest.approx(HIT_UP, abs=0.1) and names[up["other"]] == "post"
    assert math.degrees(dn["q"]) == pytest.approx(HIT_DN, abs=0.1) and names[dn["other"]] == "post"
    assert names[up["moving"]] == "arm_link"
    # the shaft rides in the bearing: listed, not tracked, and unchanged at both ends
    assert {(names[x["moving"]], names[x["other"]]) for x in r["riding"]} >= {("shaft_8mm", "608ZZ")}
    assert all(not o["grows"] for e in r["ends"].values() for o in e["riding_overlap"])
    # clearance curve: monotone towards each post from the CAD pose
    qs = [math.degrees(s["q"]) for s in r["samples"]]
    assert qs == sorted(qs) and min(qs) < -100 and max(qs) > 40
    assert {f["severity"] for f in found} == {"major"} and len(found) == 2
    assert found[0]["measured"]["unit"] == "deg" and found[0]["expected"]["basis"] == "the sim model's range"


def test_a_limit_at_the_collision_is_a_stop_and_editing_makes_the_sweep_stale(client, tmp_path):
    rid, names = _revision(client, tmp_path)
    row, r, found, _ = _confirm_and_sweep(client, rid, upper=math.radians(HIT_UP), lower=math.radians(-90),
                                         limits_source="drawing JD-12 rev B")
    assert r["collisions"]["lower"] is None and r["ends"]["lower"]["reached_limit"]
    assert [f["severity"] for f in found] == ["info"] and "hard stop" in found[0]["title"]
    # a changed spec makes the stored sweep stale: the check stops judging it
    spec = row["candidate"] | {"upper": math.radians(30), "lower": math.radians(-90), "limits_source": "drawing JD-12 rev C"}
    spec = {k: v for k, v in spec.items() if k not in ("body", "parent", "evidence")}
    m = client.put(f"/api/revisions/{rid}/motion/joints", headers=H, json=spec).json()
    assert m["joints"][0]["stale"] is True
    f = client.get(f"/api/revisions/{rid}/findings", headers=H).json()
    assert not [x for x in f["findings"] if x["check_id"] == "CM-JOINT-SWEEP"]


def test_confirmation_is_validated(client, tmp_path):
    rid, _ = _revision(client, tmp_path)
    (row,) = client.get(f"/api/revisions/{rid}/motion", headers=H).json()["joints"]
    spec = {k: v for k, v in row["candidate"].items() if k not in ("body", "parent", "evidence")}
    assert client.put(f"/api/revisions/{rid}/motion/joints", headers=H, json=spec | {"limits_source": ""}).status_code == 422
    assert client.put(f"/api/revisions/{rid}/motion/joints", headers=H, json=spec | {"cad_q": 5.0}).status_code == 422
    assert client.put(f"/api/revisions/{rid}/motion/joints", headers=H, json=spec | {"moving": ["i9999"]}).status_code == 422
    assert client.post(f"/api/revisions/{rid}/motion/sweeps", headers=H, json={"key": spec["key"]}).status_code == 409
