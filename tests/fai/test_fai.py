"""OrionFlow Inspect: tolerance tables, reading, CAD cross-check, revision compare,
review/sign-off and the API — on the OF-1001 sample whose answers are known."""
from __future__ import annotations

import types
import uuid
from pathlib import Path

import pytest

from fai import samples
from fai.tolerances import fit_limits, general_angle, general_linear


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("fai_sample")
    return {"a": samples.drawing("A", d / "revA.pdf"), "b": samples.drawing("B", d / "revB.pdf"),
            "step": samples.step(d / "revB.step"), "bom": samples.bom(d / "po.csv"), "dir": d}


@pytest.fixture(scope="module")
def result_b(files) -> dict:
    from fai.pipeline import run

    return run(files["b"], files["step"], files["bom"], {}, files["dir"])


def by_text(res: dict, designator: str) -> dict:
    return next(c for c in res["characteristics"] if c["designator"].startswith(designator))


# ------------------------------------------------------------------ tables

def test_iso286_and_iso2768_tables():
    assert fit_limits(30, "H7") == (0.0, 0.021)
    assert fit_limits(20, "g6") == (-0.02, -0.007)
    assert fit_limits(50, "js6") == (-0.008, 0.008)
    assert fit_limits(25, "k6") == (0.002, 0.015)
    assert fit_limits(30, "K7") is None              # not in the table: never guessed
    assert fit_limits(600, "H7") is None
    assert general_linear(120, "m") == 0.3
    assert general_linear(120.5, "m") == 0.5
    assert general_linear(0.3, "m") is None
    assert general_angle("m") == 1.0


# ------------------------------------------------------------------ read

def test_characteristics_are_ballooned_and_toleranced(result_b):
    chars = result_b["characteristics"]
    assert [c["no"] for c in chars] == list(range(1, len(chars) + 1))
    bore = by_text(result_b, "Ø30")
    assert (bore["lower"], bore["upper"], bore["tol_source"]) == (30.0, 30.021, "drawing")
    thick = next(c for c in chars if c["designator"] == "30")
    assert (thick["lower"], thick["upper"], thick["tol_source"]) == (29.8, 30.2, "general_note")   # ISO 2768-m
    basic = by_text(result_b, "160")
    assert basic["type"] == "Basic" and basic["inspect"] is False
    assert all(c["zone"] for c in chars)                       # the sheet's border zones were read
    assert result_b["general_tolerance"]["applied_class"] == "m"


def test_fit_class_is_looked_up_on_rev_a(files):
    from fai.pipeline import run

    res = run(files["a"])
    bore = by_text(res, "Ø30 H7")
    assert (bore["lower"], bore["upper"], bore["tol_source"]) == (30.0, 30.021, "iso286")
    assert all(c["cad_status"] == "no_model" for c in res["characteristics"])


# ------------------------------------------------------------------ cross-check

def test_drawing_vs_cad(result_b):
    bore = by_text(result_b, "Ø30")
    assert bore["cad_value"] == 30.4 and bore["cad_status"] == "deviates"
    holes = by_text(result_b, "4X Ø6.6")
    assert holes["cad_status"] == "agrees" and holes["cad_count"] == 4
    thread = by_text(result_b, "M8")
    assert thread["cad_value"] == 6.8 and "tap drill" in thread["cad_note"]
    assert by_text(result_b, "160")["cad_status"] == "agrees"
    assert by_text(result_b, "200")["cad_status"] == "agrees"
    crit = [f for f in result_b["findings"] if f["severity"] == "critical"]
    assert {f["rule"] for f in crit} == {"CAD-DIA", "BOM-REV"}
    assert next(f for f in crit if f["rule"] == "CAD-DIA")["char_no"] == bore["no"]


def test_no_false_alarms_on_a_matching_model(files, tmp_path):
    from fai.pipeline import run

    good = samples.step(tmp_path / "good.step", bore=30.01)
    res = run(files["b"], good, None, {}, tmp_path)
    assert not [f for f in res["findings"] if f["kind"] == "cad" and f["severity"] in ("critical", "major")]


def test_revision_compare(files, result_b):
    from fai.compare import compare
    from fai.pipeline import run

    a = run(files["a"])
    diff = compare(a["characteristics"], result_b["characteristics"])
    changed = {r["new"]["designator"] for r in diff["rows"] if r["status"] == "changed"}
    assert any(d.startswith("120") for d in changed)
    assert any(d.startswith("Ø30") for d in changed)
    assert any(d.startswith("M8") for d in changed)
    assert diff["counts"]["added"] == 0 and diff["counts"]["removed"] == 0


# ------------------------------------------------------------------ review and sign-off

@pytest.fixture()
def store(tmp_path, monkeypatch):
    from fai import service

    monkeypatch.setattr(service, "ROOT", tmp_path / "store")
    return service


def _revision(store, files, owner="u1"):
    p = store.create_project(owner, "OF-1001", "Bracket", "Acme", "qe@x")
    r = store.create_revision(owner, p["id"], ("b.pdf", files["b"].read_bytes()), ("b.step", files["step"].read_bytes()),
                              ("po.csv", files["bom"].read_bytes()), {}, "B", "qe@x", background=False)
    return p, r


def test_review_edit_decide_sign(store, files):
    p, r = _revision(store, files)
    rid = r["id"]
    assert r["status"] == "done"
    res = r["result"]
    bore = by_text(res, "Ø30")["no"]
    c = store.edit_characteristic("u1", rid, bore, {"result": "30.012"}, "qe@x")
    assert c["status"] == "pass"
    c = store.edit_characteristic("u1", rid, bore, {"result": "30.05"}, "qe@x")
    assert c["status"] == "fail"
    with pytest.raises(store.Conflict, match="critical"):
        store.sign("u1", rid, "R. Kumar", "QE")
    for f in res["findings"]:
        if f["severity"] == "critical":
            store.decide_finding("u1", rid, f["id"], "accepted", "customer query raised", "qe@x")
    with pytest.raises(store.Conflict, match="nonconformance"):
        store.sign("u1", rid, "R. Kumar", "QE")
    store.edit_characteristic("u1", rid, bore, {"nc_number": "NCR-118"}, "qe@x")
    so = store.sign("u1", rid, "R. Kumar", "QE", "qe@x")
    assert so["fai_scope"] == "Partial FAI"                     # other characteristics still open
    for name in ("fai.xlsx", "fai.pdf", "ballooned.pdf"):
        assert store.file_path("u1", rid, name).stat().st_size > 1000
    with pytest.raises(store.Conflict):
        store.edit_characteristic("u1", rid, bore, {"result": "30.0"})
    with pytest.raises(store.Conflict):
        store.delete_revision("u1", rid)
    actions = [e["action"] for e in store.get_project("u1", p["id"])["events"]]
    for a in ("project_created", "revision_uploaded", "revision_checked", "characteristic_edited",
              "finding_decided", "revision_signed"):
        assert a in actions


def test_ignore_for_customer_carries_to_the_next_revision(store, files):
    p, r = _revision(store, files)
    f = next(f for f in r["result"]["findings"] if f["rule"] == "BOM-MAT")
    store.decide_finding("u1", r["id"], f["id"], "ignored", "Acme writes EN8", "qe@x", for_customer=True)
    r2 = store.create_revision("u1", p["id"], ("b.pdf", files["b"].read_bytes()), None,
                               ("po.csv", files["bom"].read_bytes()), {}, "B2", "qe@x", background=False)
    f2 = next(f for f in r2["result"]["findings"] if f["rule"] == "BOM-MAT")
    assert f2["decision"] == "ignored"
    assert r2["drawing_changed"] is False                        # same file hash as the previous revision


def test_projects_are_private(store, files):
    p, r = _revision(store, files, owner="u1")
    assert store.list_projects("u2") == []
    with pytest.raises(store.NotFound):
        store.get_revision("u2", r["id"])
    with pytest.raises(store.NotFound):
        store.get_project("u2", p["id"])


# ------------------------------------------------------------------ API

def test_api_end_to_end(store, files, monkeypatch):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.main import app

    uid = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id=uid, email="qe@example.com")
    try:
        c = TestClient(app)
        p = c.post("/api/v1/fai/projects", json={"part_number": "OF-1001", "customer": "Acme"}).json()
        bad = c.post(f"/api/v1/fai/projects/{p['id']}/revisions", files={"drawing": ("x.pdf", b"nope", "application/pdf")})
        assert bad.status_code == 415
        monkeypatch.setattr(store, "_spawn", lambda fn, *args: fn(*args))
        r = c.post(f"/api/v1/fai/projects/{p['id']}/revisions",
                   files={"drawing": ("b.pdf", files["b"].read_bytes(), "application/pdf"),
                          "step": ("b.step", files["step"].read_bytes(), "application/octet-stream")},
                   data={"standard": "ISO GPS"})
        assert r.status_code == 202, r.text
        rev = c.get(f"/api/v1/fai/revisions/{r.json()['id']}").json()
        assert rev["status"] == "done" and rev["readiness"]["can_sign"] is False
        assert c.get(f"/api/v1/fai/revisions/{rev['id']}/files/model.glb").status_code == 200
        assert c.get(f"/api/v1/fai/revisions/{rev['id']}/pages/0.png").headers["content-type"] == "image/png"
        draft = c.get(f"/api/v1/fai/revisions/{rev['id']}/files/fai.xlsx")
        assert draft.status_code == 200 and len(draft.content) > 1000
        assert c.post(f"/api/v1/fai/revisions/{rev['id']}/sign", json={"name": "R"}).status_code == 409
        assert c.patch(f"/api/v1/fai/revisions/{rev['id']}/characteristics/1", json={"bogus": 1}).status_code == 400
    finally:
        app.dependency_overrides.clear()
