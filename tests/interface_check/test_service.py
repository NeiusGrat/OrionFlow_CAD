"""The platform: upload -> job -> isolated worker -> results, and every protection.

Real child processes run here (the worker's isolation is the thing under test),
so these are the slowest tests in the suite.
"""
import time
import warnings
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from interface_check import inspect_step
from interface_check.service import jobs
from interface_check.service.config import Config
from interface_check.service.dispatch import context
from interface_check.synth import build

warnings.filterwarnings("ignore", module="build123d")
DEV = {"Authorization": "Bearer devtok"}
SECRET = "test-secret"


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("IC_DEV_TOKEN", "devtok")
    monkeypatch.setenv("IC_ADMIN_USERS", "dev")
    monkeypatch.setenv("IC_JWT_SECRET", SECRET)
    monkeypatch.setenv("IC_PLAN_OVERRIDES", "u-pro=pro,u2=pro")
    from interface_check.service import plans
    plans.clear_cache()
    cfg = Config(database_url=f"sqlite:///{tmp_path / 'ic.sqlite'}", storage_root=str(tmp_path / "store"),
                 work_root=str(tmp_path / "work"))
    (tmp_path / "work").mkdir()
    ctx = context(cfg)
    from interface_check.service.api import app
    yield TestClient(app), ctx, tmp_path
    ctx.dispatcher.pool.shutdown(wait=True)


def _submit(client, files: dict, headers=DEV, **body) -> dict:
    spec = [{"kind": k, "filename": p.name, "size": p.stat().st_size} for k, p in files.items()]
    up = client.post("/api/uploads", headers=headers, json={"files": spec})
    assert up.status_code == 200, up.text
    for f, p in zip(up.json()["files"], files.values()):
        assert client.put(f["url"], headers=headers, content=p.read_bytes()).status_code == 200
    r = client.post("/api/analysis", headers=headers, json={"upload_id": up.json()["upload_id"], **body})
    assert r.status_code == 202, r.text
    return r.json()


def _wait(client, jid, headers=DEV, timeout=180) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/analysis/{jid}", headers=headers).json()
        if j["terminal"]:
            return j
        time.sleep(0.5)
    raise AssertionError(f"job {jid} not finished: {j}")


def test_end_to_end_and_idempotency(svc):
    client, ctx, tmp = svc
    o = build("bearing_joint", {"housing_bore": 22.5}, tmp / "in")
    job = _submit(client, {"step": o["step"], "bom": o["bom"]})
    j = _wait(client, job["id"])
    assert j["state"] == "SUCCEEDED", j
    assert [f["rule_id"] for f in j["findings"]] == ["BEARING_SEAT"]
    assert {s["stage"]: s["status"] for s in j["stages"]}["interface_detection"] == "FAIL"
    assert j["findings"][0]["method"]                      # every finding names its computation
    assert client.get(f"/api/analysis/{job['id']}/files/report.pdf", headers=DEV).content[:4] == b"%PDF"
    runs = ctx.store.worker_runs()
    assert len(runs) == 1 and runs[0]["peak_memory_mb"] > 0 and runs[0]["outcome"] == "SUCCEEDED"
    m = client.get("/api/admin/metrics", headers=DEV).json()
    assert m["runs"] == 1 and m["latency_s"]["p50"] > 0
    # the same request again is the same job
    again = client.post("/api/analysis", headers={**DEV, "Idempotency-Key": "k1"},
                        json={"upload_id": "0" * 32})
    assert again.status_code == 400                       # unknown upload, nothing created


def test_memory_cap_kills_child_and_escalates_until_plan_limit(svc, monkeypatch):
    client, ctx, tmp = svc
    monkeypatch.setenv("IC_LIMIT_PRO_MAX_MEMORY_MB", "120")      # below what the kernel needs
    tok = jwt.encode({"sub": "u-pro", "type": "access"}, SECRET, algorithm="HS256")
    h = {"Authorization": f"Bearer {tok}"}
    o = build("motor_mount", {}, tmp / "in")
    j = _wait(client, _submit(client, {"step": o["step"]}, headers=h)["id"], headers=h)
    assert j["state"] == "RESOURCE_LIMIT" and j["failure_code"] == "MEMORY_LIMIT", j
    tiers = [r["tier"] for r in sorted(ctx.store.worker_runs(), key=lambda r: r["attempt"])]
    assert tiers == ["SMALL", "MEDIUM", "LARGE"]               # pro plan stops at LARGE


def test_timeout_is_terminal_on_free_plan(svc, monkeypatch):
    client, ctx, tmp = svc
    monkeypatch.setenv("IC_LIMIT_FREE_MAX_RUNTIME_S", "1")
    o = build("motor_mount", {}, tmp / "in")
    j = _wait(client, _submit(client, {"step": o["step"]})["id"])
    assert j["state"] == "TIMEOUT" and j["attempts"] == 1      # free plan cannot escalate


def test_truncated_step_fails_once_without_retry(svc):
    client, ctx, tmp = svc
    o = build("motor_mount", {}, tmp / "in")
    bad = tmp / "truncated.step"
    bad.write_bytes(o["step"].read_bytes()[:4000])
    j = _wait(client, _submit(client, {"step": bad})["id"])
    assert j["state"] == "FAILED" and j["failure_code"] == "CORRUPTED_FILE" and j["attempts"] == 1


def test_routing_to_larger_tier_before_heavy_work(svc, monkeypatch):
    client, ctx, tmp = svc
    monkeypatch.setitem(inspect_step.COST_MODEL, "base_gb", 7.0)   # every file now needs > 6.4 GB
    tok = jwt.encode({"sub": "u2", "type": "access"}, SECRET, algorithm="HS256")
    h = {"Authorization": f"Bearer {tok}"}
    o = build("motor_mount", {}, tmp / "in")
    j = _wait(client, _submit(client, {"step": o["step"]}, headers=h)["id"], headers=h)
    assert j["state"] == "SUCCEEDED" and j["tier"] == "MEDIUM", j     # 11.2 GB estimate fits 16 GB x 0.8
    outcomes = [r["outcome"] for r in sorted(ctx.store.worker_runs(), key=lambda r: r["started_at"])]
    assert outcomes == ["ROUTED", "SUCCEEDED"]


def test_free_plan_refuses_what_needs_a_bigger_worker(svc, monkeypatch):
    client, ctx, tmp = svc
    monkeypatch.setitem(inspect_step.COST_MODEL, "base_gb", 7.0)
    o = build("motor_mount", {}, tmp / "in")
    j = _wait(client, _submit(client, {"step": o["step"]})["id"])
    assert j["state"] == "RESOURCE_LIMIT" and "free plan" in j["error"]


def test_per_user_concurrency_queues_and_cancel(svc, monkeypatch):
    client, ctx, tmp = svc
    o = build("motor_mount", {}, tmp / "in")
    first = _submit(client, {"step": o["step"]})
    second = _submit(client, {"step": o["step"]}, label="second")
    assert client.get(f"/api/analysis/{second['id']}", headers=DEV).json()["state"] == "QUEUED"
    third = _submit(client, {"step": o["step"]}, label="third")
    assert client.post(f"/api/analysis/{third['id']}/cancel", headers=DEV).json()["state"] == "CANCELLED"
    assert _wait(client, first["id"])["state"] == "SUCCEEDED"
    assert _wait(client, second["id"])["state"] == "SUCCEEDED"   # pumped when the first finished
    assert len(ctx.store.worker_runs()) == 2                     # the cancelled job never ran


def test_daily_quota(svc, monkeypatch):
    client, ctx, tmp = svc
    monkeypatch.setenv("IC_LIMIT_FREE_DAILY_JOBS", "1")
    o = build("motor_mount", {}, tmp / "in")
    _submit(client, {"step": o["step"]})
    spec = [{"kind": "step", "filename": "a.step", "size": 10}]
    up = client.post("/api/uploads", headers=DEV, json={"files": spec}).json()
    client.put(up["files"][0]["url"], headers=DEV, content=o["step"].read_bytes())
    r = client.post("/api/analysis", headers=DEV, json={"upload_id": up["upload_id"]})
    assert r.status_code == 429


def test_upload_validation(svc):
    client, ctx, tmp = svc
    assert client.post("/api/uploads", headers=DEV, json={"files": [
        {"kind": "step", "filename": "a.zip", "size": 10}]}).status_code == 415
    assert client.post("/api/uploads", headers=DEV, json={"files": [
        {"kind": "step", "filename": "a.step", "size": 10 * 2**30}]}).status_code == 413
    assert client.post("/api/uploads", headers=DEV, json={"files": [
        {"kind": "bom", "filename": "b.csv", "size": 10}]}).status_code == 400          # no STEP
    fake = tmp / "fake.step"
    fake.write_bytes(b"PK\x03\x04 this is a zip")
    up = client.post("/api/uploads", headers=DEV, json={"files": [
        {"kind": "step", "filename": "fake.step", "size": fake.stat().st_size}]}).json()
    client.put(up["files"][0]["url"], headers=DEV, content=fake.read_bytes())
    assert client.post("/api/analysis", headers=DEV, json={"upload_id": up["upload_id"]}).status_code == 415


def test_auth_and_isolation_between_users(svc):
    client, ctx, tmp = svc
    assert client.get("/api/analysis").status_code == 401
    assert client.get("/api/analysis", headers={"Authorization": "Bearer nope"}).status_code == 401
    refresh = jwt.encode({"sub": "u1", "type": "refresh"}, SECRET, algorithm="HS256")
    assert client.get("/api/analysis", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    job, _ = ctx.store.create_job("someone-else", "free", "SMALL", {}, None, "x")
    assert client.get(f"/api/analysis/{job['id']}", headers=DEV).status_code == 404
    tok = jwt.encode({"sub": "u1", "type": "access"}, SECRET, algorithm="HS256")
    assert client.get("/api/analysis", headers={"Authorization": f"Bearer {tok}"}).json() == []
    assert client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_sweep_recovers_a_lost_worker(svc):
    client, ctx, tmp = svc
    job, _ = ctx.store.create_job("dev", "free", "SMALL", {}, None, "lost")
    old = datetime.now(timezone.utc) - timedelta(minutes=4)      # silent past the 180 s grace, inside 600 s runtime
    ctx.store.update(job["id"], state="RUNNING", attempts=1, started_at=old, heartbeat_at=old)

    class NullDispatch:
        def submit(self, job_id, tier):
            return "null"
    out = jobs.sweep(ctx.store, NullDispatch(), 5)
    j = ctx.store.get_job(job["id"])
    assert out["stale"] == 1 and j["state"] == "QUEUED" and j["dispatch_ref"] == "null"
    lost = [r for r in ctx.store.worker_runs() if r["job_id"] == job["id"]]
    assert [(r["outcome"], r["failure_code"]) for r in lost] == [("LOST", "WORKER_FAILURE")]


@pytest.mark.parametrize("code,plan,tier,expect", [
    ("INVALID_STEP", "pro", "SMALL", ("final", "FAILED")),
    ("UNSUPPORTED_MESH", "pro", "SMALL", ("final", "UNSUPPORTED")),
    ("WORKER_FAILURE", "free", "SMALL", ("retry", "SMALL")),
    ("MEMORY_LIMIT", "pro", "SMALL", ("retry", "MEDIUM")),
    ("MEMORY_LIMIT", "pro", "LARGE", ("final", "RESOURCE_LIMIT")),
    ("MEMORY_LIMIT", "free", "SMALL", ("final", "RESOURCE_LIMIT")),
    ("TIMEOUT", "enterprise", "LARGE", ("retry", "EXTREME")),
])
def test_retry_policy(code, plan, tier, expect):
    d = jobs.after_failure({"attempts": 1, "tier": tier, "plan": plan}, code, tier_attempts=1)
    assert (d.action, d.tier or d.state) == expect


def test_plan_comes_from_the_server_not_the_token(svc, monkeypatch):
    from interface_check.service.auth import current_user
    claimed = jwt.encode({"sub": "u-nobody", "type": "access", "plan": "enterprise"}, SECRET, algorithm="HS256")
    u = current_user(f"Bearer {claimed}")
    assert (u.plan, u.plan_source) == ("free", "default")
    u = current_user("Bearer " + jwt.encode({"sub": "u-pro", "type": "access"}, SECRET, algorithm="HS256"))
    assert (u.plan, u.plan_source) == ("pro", "operator")


def test_operator_defined_plans(monkeypatch):
    from interface_check.limits import limits_for
    monkeypatch.setenv("IC_EXTRA_PLANS", '{"qa_timeout": {"base": "pro", "max_runtime_s": 2}}')
    lim = limits_for("qa_timeout")
    assert lim.plan == "qa_timeout" and lim.max_runtime_s == 2 and lim.max_tier == "LARGE"
