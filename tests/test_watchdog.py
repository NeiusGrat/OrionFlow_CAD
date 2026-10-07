"""The watchdog wiring: engines mounted in the main app, one sign-in, per-user runs."""
from __future__ import annotations

import json
import time
import types
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("IC_DATABASE_URL", f"sqlite:///{(tmp_path / 'ic.sqlite').as_posix()}")
    monkeypatch.setenv("IC_STORAGE_ROOT", str(tmp_path / "ic_store"))
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{(tmp_path / 'review.sqlite').as_posix()}")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "review_store"))
    import drawcheck.api as dc
    import review.api as rv
    from interface_check.service.dispatch import context

    from app.main import app            # shares the JWT secret with the engines on import
    from app.watchdog import robot

    monkeypatch.setattr(dc, "DATA", tmp_path / "drawcheck")
    monkeypatch.setattr(rv, "_store", None)
    context(reset=True)

    monkeypatch.setattr(robot, "DATA", tmp_path / "robot")
    yield TestClient(app), dc, robot
    app.dependency_overrides.clear()
    context(reset=True)


def _bearer(uid: str) -> dict:
    from app.auth.jwt import create_access_token

    return {"Authorization": f"Bearer {create_access_token(uid, f'{uid[:4]}@example.com')}"}


def test_engines_are_mounted_and_accept_main_app_tokens(client):
    c, _, _ = client
    from app.watchdog.engines import STATUS

    assert STATUS == {"interface_check": None, "review": None, "drawcheck": None}
    assert c.get("/verify/api/analysis").status_code == 401
    assert c.get("/drawing/api/runs").status_code == 401
    assert c.get("/review/api/projects").status_code == 401
    me = _bearer(str(uuid.uuid4()))
    assert c.get("/verify/api/analysis", headers=me).json() == []
    assert c.get("/drawing/api/runs", headers=me).json() == []
    assert c.get("/review/api/projects", headers=me).json() == []
    made = c.post("/review/api/projects", json={"name": "Arm"}, headers=me).json()
    assert [p["id"] for p in c.get("/review/api/projects", headers=me).json()] == [made["id"]]
    other = _bearer(str(uuid.uuid4()))
    assert c.get(f"/review/api/projects/{made['id']}", headers=other).status_code == 404


def test_a_forged_token_is_refused(client):
    c, _, _ = client
    import jwt

    forged = jwt.encode({"sub": "x", "type": "access", "exp": time.time() + 60}, "not-the-secret", algorithm="HS256")
    h = {"Authorization": f"Bearer {forged}"}
    assert c.get("/verify/api/analysis", headers=h).status_code == 401
    assert c.get("/drawing/api/runs", headers=h).status_code == 401
    assert c.get("/review/api/projects", headers=h).status_code == 401


def test_drawing_runs_are_visible_only_to_their_owner(client):
    c, dc, _ = client
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    d = dc.DATA / "abc123def456"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": "abc123def456", "filename": "x.pdf", "customer": "",
                                             "vision": "off", "status": "done", "created": time.time(),
                                             "owner": a}))
    assert [r["id"] for r in c.get("/drawing/api/runs", headers=_bearer(a)).json()] == ["abc123def456"]
    assert c.get("/drawing/api/runs", headers=_bearer(b)).json() == []
    assert c.get("/drawing/api/runs/abc123def456", headers=_bearer(b)).status_code == 404
    assert c.delete("/drawing/api/runs/abc123def456", headers=_bearer(b)).status_code == 404
    assert d.exists()


def test_robot_runs_are_per_user_and_validated(client):
    c, _, robot = client
    from app.auth.dependencies import get_current_user
    from app.main import app

    who = {"id": uuid.uuid4()}
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id=who["id"])
    r = c.post("/api/v1/watchdog/robot/runs", data={"mode": "check"},
               files={"file": ("robot.urdf", b"not xml", "application/xml")})
    assert r.status_code == 415
    assert c.post("/api/v1/watchdog/robot/runs", data={"mode": "fly"}).status_code == 400

    d = robot._user_dir(str(who["id"])) / "0123456789ab"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": "0123456789ab", "mode": "check", "label": "r", "status": "done",
                                             "created": time.time()}))
    assert [x["id"] for x in c.get("/api/v1/watchdog/robot/runs").json()] == ["0123456789ab"]
    who["id"] = uuid.uuid4()
    assert c.get("/api/v1/watchdog/robot/runs").json() == []
    assert c.get("/api/v1/watchdog/robot/runs/0123456789ab").status_code == 404
    assert c.get("/api/v1/watchdog/robot/runs/../../etc/files/model.glb").status_code == 404


def test_samples_are_listed(client):
    c, _, _ = client
    from app.auth.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id=uuid.uuid4())
    ids = {s["id"] for s in c.get("/api/v1/watchdog/samples").json()}
    assert ids == {"robot_joint", "chassis", "motor_mount"}
    assert c.post("/api/v1/watchdog/samples/nope").status_code == 404
