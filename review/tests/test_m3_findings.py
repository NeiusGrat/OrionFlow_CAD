"""M3: the check engine's rules, the D1 structure checks, and findings through the API."""
from __future__ import annotations

import pytest

from review.checks import base
from review.checks.base import CheckConfig, Evidence, Finding, Quantity, run_checks
from review.schema import Bbox, Instance, ModelGraph, Part, SourceFile, Stats, TreeNode

I4 = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def T(x=0.0, y=0.0, z=0.0):
    return [[1.0, 0, 0, x], [0, 1.0, 0, y], [0, 0, 1.0, z], [0, 0, 0, 1.0]]


def part(pid, name, size=(10, 10, 10), h=None, vol=None):
    return Part(id=pid, name=name, hash=h or f"h-{pid}", volume=vol or float(size[0] * size[1] * size[2]),
                area=1.0, bbox=Bbox(min=[0, 0, 0], max=list(map(float, size))), com=[0, 0, 0])


def graph(parts, placements):
    insts = []
    for n, (pid, tr) in enumerate(placements, start=1):
        p = next(x for x in parts if x.id == pid)
        x, y, z = tr[0][3], tr[1][3], tr[2][3]
        insts.append(Instance(id=f"i{n:04d}", part_id=pid, path=f"asm/{p.name}#{n}", name=p.name, transform=tr,
                              bbox=Bbox(min=[x, y, z], max=[x + p.bbox.max[0], y + p.bbox.max[1], z + p.bbox.max[2]])))
    return ModelGraph(revision_id="r", source=SourceFile(name="a.step", kind="step", sha256="0" * 64, size=1),
                      stats=Stats(parts=len(parts), instances=len(insts), assemblies=1, max_depth=2),
                      parts=parts, instances=insts, tree=TreeNode(key="asm", name="asm"))


def by(findings, cid):
    return [f for f in findings if f.check_id == cid]


# ------------------------------------------------------------------ engine --

def test_finding_without_evidence_is_refused():
    with pytest.raises(ValueError):
        Finding(check_id="X", check_version="1", domain="structure", severity="minor", title="t", statement="s", evidence=[])


def test_engine_reports_not_run_with_a_reason():
    g = graph([part("p1", "plate")], [("p1", I4)])
    _, runs = run_checks(g)
    assert {r["check_id"]: r["status"] for r in runs}["ST-TREE"] == "passed"
    # a check that needs a BOM is not run, with the reason, when there is none
    base.REGISTRY["T-NEEDS-BOM"] = base.Check("T-NEEDS-BOM", "1.0.0", "documentation", "needs bom", ["bom_rows"],
                                              "deterministic", lambda g, c: [])
    try:
        _, runs = run_checks(g)
        rec = next(r for r in runs if r["check_id"] == "T-NEEDS-BOM")
        assert rec["status"] == "not_run" and "BOM" in rec["reason"]
    finally:
        base.REGISTRY.pop("T-NEEDS-BOM")


def test_deterministic_finding_needs_measured_and_expected_and_a_broken_check_is_isolated():
    def bad(g, c):
        return [Finding(check_id="T-BAD", check_version="1.0.0", domain="structure", severity="major", title="t",
                        statement="no numbers", evidence=[Evidence(type="part", id="p1")])]
    base.REGISTRY["T-BAD"] = base.Check("T-BAD", "1.0.0", "structure", "bad", [], "deterministic", bad)
    try:
        findings, runs = run_checks(graph([part("p1", "plate")], [("p1", I4)]))
        rec = next(r for r in runs if r["check_id"] == "T-BAD")
        assert rec["status"] == "error" and "measured and expected" in rec["error"]
        assert not by(findings, "T-BAD")
        assert next(r for r in runs if r["check_id"] == "ST-TREE")["status"] == "passed"   # the others still ran
    finally:
        base.REGISTRY.pop("T-BAD")


def test_fingerprint_is_stable_and_specific():
    a = Finding(check_id="X", check_version="1", domain="structure", severity="info", title="t", statement="s",
                evidence=[Evidence(type="part", id="p1"), Evidence(type="part", id="p2")])
    b = Finding(check_id="X", check_version="2", domain="structure", severity="info", title="other", statement="other",
                evidence=[Evidence(type="part", id="p2"), Evidence(type="part", id="p1")])
    c = Finding(check_id="X", check_version="1", domain="structure", severity="info", title="t", statement="s",
                evidence=[Evidence(type="part", id="p3")])
    assert a.fingerprint == b.fingerprint != c.fingerprint


# --------------------------------------------------------------- D1 checks --

def test_st_tree_unnamed_samename_samehash_and_mirror_pairs():
    parts = [part("p1", "SOLID1"), part("p2", "BRACKET", (10, 10, 10), h="A"), part("p3", "BRACKET", (12, 10, 10), h="B"),
             part("p4", "SPACER_A", h="S", vol=50), part("p5", "SPACER_OLD", h="S", vol=50),
             part("p6", "FLAP_L", h="M", vol=70), part("p7", "FLAP_R", h="M", vol=70)]
    g = graph(parts, [(p.id, T(x=20 * k)) for k, p in enumerate(parts)])
    f = by(run_checks(g, only=["ST-TREE"])[0], "ST-TREE")
    titles = sorted(x.title for x in f)
    assert titles == ["One name, different shapes", "Part has no meaningful name", "Same shape, different names"]
    same = next(x for x in f if x.title == "Same shape, different names")
    assert {e.id for e in same.evidence} == {"p4", "p5"}          # FLAP_L / FLAP_R are a mirror pair, not flagged
    name = next(x for x in f if x.title == "One name, different shapes")
    assert name.severity == "major" and name.measured.value == 2 and name.expected.value == 1


def test_st_dup_body_catches_a_copy_at_the_same_place():
    parts = [part("p1", "BOLT_M3", (3, 3, 10))]
    g = graph(parts, [("p1", T(5, 5, 0)), ("p1", T(5, 5, 0)), ("p1", T(25, 5, 0))])
    f = by(run_checks(g, only=["ST-DUP-BODY"])[0], "ST-DUP-BODY")
    assert len(f) == 1 and {e.id for e in f[0].evidence} == {"i0001", "i0002"}
    assert f[0].measured.value == 0 and f[0].severity == "major"


def test_st_units_catches_wrong_units():
    parts = [part("p1", "plate", (0.2, 0.1, 0.005)), part("p2", "speck", (0.001, 0.001, 0.001))]
    g = graph(parts, [("p1", I4), ("p2", T(0.05, 0, 0))])
    f = by(run_checks(g, only=["ST-UNITS"])[0], "ST-UNITS")
    titles = {x.title for x in f}
    assert "Assembly size is implausible" in titles and "Part is far too small to be real" in titles
    crit = next(x for x in f if x.severity == "critical")
    assert crit.measured.value < 1 and crit.expected.min == 1.0


def test_clean_graph_has_no_structure_findings():
    parts = [part("p1", "BASE_PLATE", (100, 80, 6)), part("p2", "BOLT_M4x12", (7, 7, 16))]
    g = graph(parts, [("p1", I4)] + [("p2", T(10 + 20 * k, 10, 6)) for k in range(4)])
    findings, runs = run_checks(g)
    assert [x for x in findings if x.domain == "structure"] == []
    assert all(r["status"] == "passed" for r in runs if r["domain"] == "structure")


def test_config_is_quoted_as_the_basis():
    parts = [part("p1", "speck", (0.01, 0.01, 0.01)), part("p2", "plate", (50, 50, 5))]
    g = graph(parts, [("p1", I4), ("p2", T(10, 0, 0))])
    f = by(run_checks(g, CheckConfig({"unit_tiny_mm": 0.02}), only=["ST-UNITS"])[0], "ST-UNITS")
    assert f[0].expected.basis == "project setting: unit_tiny_mm = 0.02"


# --------------------------------------------------------------------- API --

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/r.sqlite")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("REVIEW_DEV_TOKEN", "t")
    monkeypatch.setenv("REVIEW_INLINE", "1")
    import review.api as api
    monkeypatch.setattr(api, "_store", None)
    saved = dict(api.app.dependency_overrides)
    api.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(saved)


H = {"Authorization": "Bearer t"}


@pytest.fixture(scope="module")
def dup_step(tmp_path_factory):
    """Two identical brackets at one placement (a copy-paste error) plus a properly named base."""
    from build123d import Box, Compound, Location, Pos, export_step
    base_ = Pos(0, 0, 2.5) * Box(100, 60, 5)
    base_.label = "BASE_PLATE"
    br = Pos(0, 0, 15) * Box(20, 10, 20)
    a = br.moved(Location((0, 0, 0)))
    a.label = "BRACKET"
    b = br.moved(Location((0, 0, 0)))
    b.label = "BRACKET"
    asm = Compound(children=[base_, a, b])
    asm.label = "dup_asm"
    path = tmp_path_factory.mktemp("dup") / "dup.step"
    export_step(asm, str(path).replace("\\", "/"))
    return path


def test_findings_flow(client, dup_step):
    p = client.post("/api/projects", json={"name": "Dup"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                      files=[("files", ("dup.step", dup_step.read_bytes()))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert job["state"] == "done", job
    assert job["steps"][-1]["key"] == "checks" and "findings" in job["steps"][-1]["note"]

    data = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()
    dup = [f for f in data["findings"] if f["check_id"] == "ST-DUP-BODY"]
    assert len(dup) == 1 and dup[0]["severity"] == "major" and len(dup[0]["evidence"]) == 2
    runs = {r["check_id"]: r for r in data["check_runs"]}
    assert runs["ST-DUP-BODY"]["status"] == "findings" and runs["ST-DUP-BODY"]["check_version"] == "1.1.0"
    assert data["summary"]["major"] >= 1
    fid = dup[0]["id"]

    # reject needs a reason
    assert client.patch(f"/api/findings/{fid}", json={"status": "rejected"}, headers=H).status_code == 422
    out = client.patch(f"/api/findings/{fid}", json={"status": "accepted", "note": "real: delete the copy"}, headers=H).json()
    assert out["status"] == "accepted"
    out = client.post(f"/api/findings/{fid}/comments", json={"text": "assigned to mech"}, headers=H).json()
    out = client.patch(f"/api/findings/{fid}", json={"owner": "sahil"}, headers=H).json()
    actions = [e["action"] for e in out["events"]]
    assert actions == ["detected", "status", "comment", "owner"]
    assert out["events"][1]["from_status"] == "open" and out["events"][1]["to_status"] == "accepted"
    assert out["events"][1]["note"] == "real: delete the copy" and out["owner"] == "sahil"

    # a re-run keeps the decision (same fingerprint, same id, same status)
    client.post(f"/api/revisions/{rev['id']}/run", headers=H)
    again = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()
    same = next(f for f in again["findings"] if f["check_id"] == "ST-DUP-BODY")
    assert same["id"] == fid and same["status"] == "accepted"

    rep = client.get(f"/api/revisions/{rev['id']}/report.json", headers=H)
    assert rep.status_code == 200 and "attachment" in rep.headers["content-disposition"]
    body = rep.json()
    assert body["inputs"][0]["sha256"] and body["model_graph"]["schema_version"]
    assert any(c["check_id"] == "ST-DUP-BODY" and c["check_version"] for c in body["check_runs"])
    f = next(x for x in body["findings"] if x["id"] == fid)
    assert [e["action"] for e in f["events"]] == ["detected", "status", "comment", "owner"]


def test_findings_are_private(client, dup_step):
    import review.api as api
    p = client.post("/api/projects", json={"name": "Mine"}, headers=H).json()
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                      files=[("files", ("dup.step", dup_step.read_bytes()))]).json()
    client.post(f"/api/revisions/{rev['id']}/run", headers=H)
    fid = client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()["findings"][0]["id"]
    client.app.dependency_overrides[api.owner] = lambda: "intruder"
    try:
        assert client.get(f"/api/findings/{fid}").status_code == 404
        assert client.patch(f"/api/findings/{fid}", json={"status": "fixed"}).status_code == 404
        assert client.get(f"/api/revisions/{rev['id']}/report.json").status_code == 404
    finally:
        client.app.dependency_overrides.pop(api.owner, None)


def test_flat_file_gets_one_structure_finding_not_name_noise():
    parts = [part("p1", "dump_body1", h="A"), part("p2", "dump_body2", h="A")]
    g = graph(parts, [("p1", I4), ("p2", T(30, 0, 0))])
    g.stats.flat = True
    f = by(run_checks(g, only=["ST-TREE"])[0], "ST-TREE")
    assert [x.title for x in f] == ["No assembly structure in the file"] and f[0].severity == "major"


def test_dup_body_uses_world_position_not_transform():
    # two bodies of one shape, both with identity transforms but geometry in different places (a flat file's
    # split copies): not duplicates
    a = part("p1", "body", (10, 10, 10), h="S")
    b = part("p2", "body_copy", (10, 10, 10), h="S")
    b.com = [50.0, 0.0, 0.0]
    a.com = [5.0, 5.0, 5.0]
    g = graph([a, b], [("p1", I4), ("p2", I4)])
    assert by(run_checks(g, only=["ST-DUP-BODY"])[0], "ST-DUP-BODY") == []
