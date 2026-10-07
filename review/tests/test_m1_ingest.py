"""M1: classify + hash uploads, STEP -> Model Graph + GLB, and the API end to end.

Fixtures are build123d assemblies with known answers (interface_check.synth),
so the counts asserted here are facts about the geometry, not snapshots.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from review.ingest import build_graph, classify, expand_zip, sha256_file

TOKEN = "test-token"


@pytest.fixture(scope="module")
def chassis(tmp_path_factory):
    from interface_check.synth import build
    out = build("chassis", {}, tmp_path_factory.mktemp("chassis"))
    return out


# ---------------------------------------------------------------- classify --

@pytest.mark.parametrize("name,head,kind", [
    ("a.STEP", b"", "step"),
    ("weird.txt", b"ISO-10303-21;\nHEADER;", "step"),
    ("guide.pdf", b"%PDF-1.7", "pdf"),
    ("robot.urdf", b"<robot name='x'>", "urdf"),
    ("scene.xml", b"<mujoco model='yubi'>", "mjcf"),
    ("robot.xml", b"<?xml version='1.0'?><robot name='r'>", "urdf"),
    ("config.xml", b"<config/>", "other"),
    ("bom.csv", b"No,Part,Qty", "bom"),
    ("BOM.md", b"| No. | PART No. | Qty. |\n| --- | --- | --- |", "bom"),
    ("README.md", b"# hello\nno tables here", "other"),
    ("finger.stl", b"solid finger", "mesh"),
    ("photo.png", b"\x89PNG", "other"),
])
def test_classify(name, head, kind):
    assert classify(name, head) == kind


def test_zip_members_are_flattened_safely():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pkg/a.step", "ISO-10303-21;")
        z.writestr("__MACOSX/pkg/._a.step", "junk")
        z.writestr("pkg/.DS_Store", "junk")
        z.writestr("../../evil.csv", "x")
    names = [n for n, _ in expand_zip(buf.getvalue())]
    assert names == ["pkg/a.step", "evil.csv"]


# ------------------------------------------------------------------- graph --

def test_graph_counts_tree_and_glb(chassis, tmp_path):
    glb = tmp_path / "v.glb"
    g = build_graph(chassis["step"], "rev1", glb_path=glb)
    names = sorted(p.name for p in g.parts)
    assert names == ["chassis_plate", "cover_plate", "side_bracket", "standoff_M3x35"]
    assert g.stats.parts == 4 and g.stats.instances == 8
    by_name = {p.name: p for p in g.parts}
    count = {n: sum(1 for i in g.instances if i.part_id == by_name[n].id) for n in names}
    assert count == {"chassis_plate": 1, "cover_plate": 1, "side_bracket": 2, "standoff_M3x35": 4}
    # plate 200 x 100 x 5 with 4x d4.2 and 4x d3.4 through holes
    import math
    hole = lambda d: math.pi * (d / 2) ** 2 * 5
    assert by_name["chassis_plate"].volume == pytest.approx(200 * 100 * 5 - 4 * hole(4.2) - 4 * hole(3.4), rel=1e-4)
    assert sorted(by_name["chassis_plate"].bbox.size) == pytest.approx([5, 100, 200], abs=1e-3)
    # the brackets and posts sub-assemblies survive as tree nodes
    assert g.stats.assemblies >= 2 and g.stats.max_depth >= 3
    leaves = []

    def walk(n):
        if n.instance:
            leaves.append(n.instance)
        for c in n.children:
            walk(c)
    walk(g.tree)
    assert sorted(leaves) == sorted(i.id for i in g.instances)
    # same geometry -> same hash; different geometry -> different hash
    assert len({p.hash for p in g.parts}) == 4
    # the viewer GLB: one node per instance, named by the instance id; one mesh per part
    import trimesh
    scene = trimesh.load(glb)
    assert sorted(scene.graph.nodes_geometry) == sorted(i.id for i in g.instances)
    assert len(scene.geometry) == 4
    assert g.stats.triangles > 0


def test_instance_bbox_is_in_assembly_frame(chassis):
    g = build_graph(chassis["step"], "rev1")
    posts = [i for i in g.instances if i.name.startswith("standoff")]
    centres = sorted((round((i.bbox.min[0] + i.bbox.max[0]) / 2), round((i.bbox.min[1] + i.bbox.max[1]) / 2))
                     for i in posts)
    from interface_check.synth import STANDOFFS
    assert centres == sorted((round(x), round(y)) for x, y in STANDOFFS)


# --------------------------------------------------------------------- API --

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/r.sqlite")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("REVIEW_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("REVIEW_INLINE", "1")
    import review.api as api
    monkeypatch.setattr(api, "_store", None)
    # the main app (if imported by another test) installs its own auth override on this sub-app
    saved = dict(api.app.dependency_overrides)
    api.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(saved)


H = {"Authorization": f"Bearer {TOKEN}"}


def test_api_requires_auth(client):
    assert client.get("/api/projects").status_code == 401


def test_api_end_to_end(client, chassis):
    p = client.post("/api/projects", json={"name": "Chassis"}, headers=H).json()
    step = chassis["step"].read_bytes()
    bom = chassis["bom"].read_bytes()
    r = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                    files=[("files", ("chassis.step", step)), ("files", ("chassis_bom.csv", bom)),
                           ("files", ("notes.txt", b"hello"))])
    assert r.status_code == 201, r.text
    rev = r.json()
    kinds = {f["name"]: f["kind"] for f in rev["files"]}
    assert kinds == {"chassis.step": "step", "chassis_bom.csv": "bom", "notes.txt": "other"}
    step_row = next(f for f in rev["files"] if f["name"] == "chassis.step")
    assert step_row["sha256"] == sha256_file(chassis["step"])

    # the user can correct a classification
    other = next(f for f in rev["files"] if f["name"] == "notes.txt")
    fixed = client.patch(f"/api/revisions/{rev['id']}/files/{other['id']}", json={"kind": "bom"}, headers=H).json()
    assert fixed["kind"] == "bom" and fixed["kind_source"] == "user"

    assert client.get(f"/api/revisions/{rev['id']}/graph", headers=H).status_code == 404
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()   # inline in tests
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert job["state"] == "done", job
    assert [s["key"] for s in job["steps"]] == ["parse", "features", "contacts", "mesh", "graph"]
    assert all(s["state"] == "done" for s in job["steps"]), job["steps"]
    assert all(s["seconds"] is not None for s in job["steps"])

    g = client.get(f"/api/revisions/{rev['id']}/graph", headers=H).json()
    assert g["stats"]["parts"] == 4 and g["stats"]["instances"] == 8
    assert g["source"]["sha256"] == step_row["sha256"]
    glb = client.get(f"/api/revisions/{rev['id']}/viewer.glb", headers=H)
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"

    proj = client.get(f"/api/projects/{p['id']}", headers=H).json()
    assert proj["revisions"][0]["status"] == "done" and proj["revisions"][0]["stats"]["instances"] == 8


def test_run_without_step_is_refused(client):
    p = client.post("/api/projects", json={"name": "Empty"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                      files=[("files", ("bom.csv", b"No,Part,Qty\n1,a,1\n"))]).json()
    r = client.post(f"/api/revisions/{rev['id']}/run", headers=H)
    assert r.status_code == 422


def test_bad_step_fails_the_job_with_a_reason(client):
    p = client.post("/api/projects", json={"name": "Broken"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                      files=[("files", ("broken.step", b"ISO-10303-21;\nnot really a step file"))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert job["state"] == "failed" and job["error"]
    assert job["steps"][0]["state"] == "failed"


def test_projects_are_private(client, monkeypatch):
    import review.api as api
    p = client.post("/api/projects", json={"name": "Mine"}, headers=H).json()
    client.app.dependency_overrides[api.owner] = lambda: "someone-else"
    try:
        assert client.get(f"/api/projects/{p['id']}").status_code == 404
        assert client.get("/api/projects").json() == []
    finally:
        client.app.dependency_overrides.pop(api.owner, None)
