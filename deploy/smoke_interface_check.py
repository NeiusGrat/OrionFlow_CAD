"""Production smoke test for the CAD analysis service, through its public API.

    python deploy/smoke_interface_check.py [--base URL] [--out smoke.json]

Path under test, every case:
    signed upload URL -> PUT to Supabase Storage -> POST /api/analysis -> Modal dispatch
    -> isolated worker -> results in Postgres + Storage -> GET status / findings / report

Cases: normal file, oversized (declared and actual), corrupt and non-STEP files,
mesh-heavy and all-mesh STEP, timeout, memory limit, worker crash and recovery,
duplicate submission, concurrent jobs from several users while another user's
job is being killed for memory, part-cache hit on a new revision, auth, plan,
quota and cross-user isolation, and anonymous-role RLS with rows present.

Tokens are minted with the deploy JWT secret for QA accounts (sub "qa-...")
whose plans come from the service's operator overrides. Reads deploy/.env.deploy;
prints no secret.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_cad_secret import ENV, load  # noqa: E402

warnings.filterwarnings("ignore")
BASE = "https://sahilmaniyar57--orionflow-cad-web.modal.run"
TERMINAL = {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "RESOURCE_LIMIT", "UNSUPPORTED"}


class Smoke:
    def __init__(self, base: str, workdir: Path):
        self.base = base.rstrip("/")
        self.env = load(ENV)
        self.secret = self.env["JWT_SECRET_KEY"]
        self.http = httpx.Client(timeout=180, follow_redirects=False)
        self.work = workdir
        self.results: list[dict] = []
        self.jobs: list[dict] = []
        self.lock = threading.Lock()

    # ------------------------------------------------------------ helpers
    def h(self, sub: str, secret: str | None = None) -> dict:
        now = int(time.time())
        tok = jwt.encode({"sub": sub, "type": "access", "iat": now, "exp": now + 7200}, secret or self.secret,
                         algorithm="HS256")
        return {"Authorization": f"Bearer {tok}"}

    def record(self, case: str, ok: bool, detail) -> None:
        with self.lock:
            self.results.append({"case": case, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {case}: {json.dumps(detail, default=str)[:400]}", flush=True)

    def upload(self, sub: str, files: dict, declared: dict | None = None) -> tuple[int, dict]:
        spec = [{"kind": k, "filename": Path(p).name, "size": (declared or {}).get(k, Path(p).stat().st_size)}
                for k, p in files.items()]
        r = self.http.post(f"{self.base}/api/uploads", headers=self.h(sub), json={"files": spec})
        if r.status_code != 200:
            return r.status_code, r.json()
        up = r.json()
        for f, p in zip(up["files"], files.values()):
            hdr = self.h(sub) if f["url"].startswith("/") else {}
            url = self.base + f["url"] if f["url"].startswith("/") else f["url"]
            pr = self.http.put(url, headers=hdr, content=Path(p).read_bytes())
            if pr.status_code not in (200, 201):
                return pr.status_code, {"put": pr.text[:200]}
        return 200, up

    def submit(self, sub: str, files: dict, idem: str | None = None, label: str = "") -> tuple[int, dict]:
        code, up = self.upload(sub, files)
        if code != 200:
            return code, up
        hdr = self.h(sub) | ({"Idempotency-Key": idem} if idem else {})
        r = self.http.post(f"{self.base}/api/analysis", headers=hdr,
                           json={"upload_id": up["upload_id"], "label": label or f"qa-smoke {Path(files['step']).stem}"})
        return r.status_code, r.json()

    def wait(self, sub: str, jid: str, timeout: float = 900) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = self.http.get(f"{self.base}/api/analysis/{jid}", headers=self.h(sub))
            if r.status_code == 200 and r.json()["terminal"]:
                j = r.json()
                j["_wall_s"] = round(time.time() - t0, 1)
                with self.lock:
                    self.jobs.append({"user": sub, **{k: j.get(k) for k in (
                        "id", "label", "plan", "state", "tier", "attempts", "failure_code", "_wall_s")},
                        "runtime_s": (j.get("stats") or {}).get("runtime_s"),
                        "peak_rss_mb": (j.get("stats") or {}).get("peak_rss_mb"),
                        "cache": (j.get("stats") or {}).get("cache")})
                return j
            time.sleep(2)
        raise TimeoutError(f"{jid} not terminal after {timeout}s")

    def run_case(self, case: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a broken case is a failed case, the rest still run
            self.record(case, False, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------ files
    def make_files(self) -> dict:
        from interface_check.synth import build as synth, mesh_body
        from build123d import Compound, Sphere, export_step
        w = self.work
        f = {"motor": synth("motor_mount", {}, w / "a", "motor_mount")["step"],
             "motor_rev": synth("motor_mount", {"corner_shift": (0, 1.0)}, w / "b", "motor_mount_revB")["step"],
             "bearing": synth("bearing_joint", {"housing_bore": 22.5}, w / "c", "bearing_joint")}
        f["bom"] = f["bearing"]["bom"]
        f["bearing"] = f["bearing"]["step"]
        f["mesh"] = synth("mesh_bracket", {"base_tap": 3.3, "mesh_tol": 0.08}, w / "d", "mesh_bracket")["step"]
        body = mesh_body(Sphere(15), 0.2)
        body.label = "scan"
        asm = Compound(children=[body])
        asm.label = "scan_only"
        f["all_mesh"] = w / "scan_only.step"
        export_step(asm, str(f["all_mesh"]).replace("\\", "/"))
        f["corrupt"] = w / "truncated.step"
        f["corrupt"].write_bytes(Path(f["motor"]).read_bytes()[:5000])
        f["zip"] = w / "archive_renamed.step"
        f["zip"].write_bytes(b"PK\x03\x04" + b"\0" * 2000)
        big = w / "oversized.step"
        with open(big, "wb") as fh:                      # 51 MB, over the free plan's 50 MB
            fh.write(b"ISO-10303-21;\nHEADER;\n/*")
            fh.write(b"x" * (51 * 2**20))
            fh.write(b"*/\nENDSEC;\nEND-ISO-10303-21;\n")
        f["oversized"] = big
        return f

    # ------------------------------------------------------------ cases
    def run(self) -> dict:
        t_all = time.time()
        f = self.make_files()
        r = self.http.get(f"{self.base}/api/health")
        self.record("api liveness", r.status_code == 200 and r.json()["ok"], r.json())

        # auth, isolation
        self.record("no token -> 401", self.http.get(f"{self.base}/api/analysis").status_code == 401, None)
        forged = self.http.get(f"{self.base}/api/analysis", headers=self.h("qa-x", "wrong-secret")).status_code
        self.record("forged token -> 401", forged == 401, forged)

        def normal():
            code, job = self.submit("qa-smoke-u1", {"step": f["motor"]})
            j = self.wait("qa-smoke-u1", job["id"])
            pdf = self.http.get(f"{self.base}/api/analysis/{job['id']}/files/report.pdf", headers=self.h("qa-smoke-u1"))
            signed = pdf.headers.get("location", "")
            body = httpx.get(signed, timeout=120).content[:4] if pdf.status_code == 307 else b""
            glb = self.http.get(f"{self.base}/api/analysis/{job['id']}/files/model.glb", headers=self.h("qa-smoke-u1"))
            ok = (code == 202 and j["state"] == "SUCCEEDED" and j["tier"] == "SMALL" and body == b"%PDF"
                  and glb.status_code == 307 and "orionflow-cad" in signed)
            self.record("normal small file -> report", ok, {"state": j["state"], "tier": j["tier"],
                        "findings": [x["rule_id"] for x in j["findings"]], "pdf_via_signed_url": body == b"%PDF",
                        "stages": sum(1 for s in j["stages"] if s["status"] in ("PASS", "FAIL", "WARNING"))})
            other = self.http.get(f"{self.base}/api/analysis/{job['id']}", headers=self.h("qa-smoke-u2")).status_code
            self.record("other user cannot read the job", other == 404, other)

            # cache: Rev B of the same assembly re-uses the unchanged parts
            code, job2 = self.submit("qa-smoke-u1", {"step": f["motor_rev"]})
            j2 = self.wait("qa-smoke-u1", job2["id"])
            cache = (j2.get("stats") or {}).get("cache", {})
            self.record("cache hit on unchanged parts", j2["state"] == "SUCCEEDED" and cache.get("hits") == 2
                        and cache.get("misses") == 1 and any(x["rule_id"] == "HOLE_MISALIGNED" for x in j2["findings"]),
                        cache)

        def oversized():
            code, body = self.upload("qa-smoke-u2", {"step": f["oversized"]}, declared={"step": 51 * 2**20})
            self.record("oversized (declared) -> 413", code == 413, body)
            # Declared small, actually 51 MB: refused either by the storage bucket's own
            # size limit on the PUT, or by the API's re-check before any job exists.
            code, up = self.upload("qa-smoke-u2", {"step": f["oversized"]}, declared={"step": 1000})
            r = self.http.post(f"{self.base}/api/analysis", headers=self.h("qa-smoke-u2"),
                               json={"upload_id": up["upload_id"]}) if code == 200 else None
            where = "storage PUT" if r is None else "job creation"
            self.record("oversized (lied about size) -> refused, no job", (code == 413 and r is None)
                        or (r is not None and r.status_code == 413), {"refused_at": where, "status": code if r is None
                                                                      else r.status_code})

        def corrupt():
            code, body = self.submit("qa-smoke-u2", {"step": f["zip"]})
            self.record("archive renamed .step -> 415", code == 415, body)
            code, job = self.submit("qa-smoke-u2", {"step": f["corrupt"]})
            j = self.wait("qa-smoke-u2", job["id"])
            self.record("truncated STEP -> FAILED once, no retry", j["state"] == "FAILED"
                        and j["failure_code"] == "CORRUPTED_FILE" and j["attempts"] == 1,
                        {k: j[k] for k in ("state", "failure_code", "attempts", "error")})

        def mesh():
            code, job = self.submit("qa-smoke-u4", {"step": f["mesh"]})
            j = self.wait("qa-smoke-u4", job["id"])
            rules = {x["rule_id"] for x in j.get("findings", [])}
            self.record("mesh-heavy STEP -> analysed, mesh skipped", j["state"] == "SUCCEEDED"
                        and "UNSUPPORTED_GEOMETRY" in rules and "FASTENER_SIZE_MISMATCH" in rules,
                        {"state": j["state"], "rules": sorted(rules), "complexity": j.get("complexity")})
            code, job = self.submit("qa-smoke-u4", {"step": f["all_mesh"]})
            j = self.wait("qa-smoke-u4", job["id"])
            self.record("all-mesh STEP -> UNSUPPORTED", j["state"] == "UNSUPPORTED"
                        and j["failure_code"] == "UNSUPPORTED_MESH", {k: j[k] for k in ("state", "failure_code")})

        def timeout():
            code, job = self.submit("qa-smoke-timeout", {"step": f["bearing"], "bom": f["bom"]})
            j = self.wait("qa-smoke-timeout", job["id"])
            self.record("timeout -> escalates, then TIMEOUT", j["state"] == "TIMEOUT" and j["attempts"] == 3,
                        {k: j[k] for k in ("state", "failure_code", "attempts", "tier", "error")})

        def memory():
            code, job = self.submit("qa-smoke-memory", {"step": f["bearing"]})
            j = self.wait("qa-smoke-memory", job["id"])
            self.record("memory limit -> SMALL, MEDIUM, LARGE, then RESOURCE_LIMIT", j["state"] == "RESOURCE_LIMIT"
                        and j["failure_code"] == "MEMORY_LIMIT" and j["attempts"] == 3,
                        {k: j[k] for k in ("state", "failure_code", "attempts", "tier", "error")})

        def concurrent():
            users = ["qa-smoke-c1", "qa-smoke-c2", "qa-smoke-c3"]
            subs = []
            with ThreadPoolExecutor(6) as ex:
                futs = [(u, ex.submit(self.submit, u, {"step": f["bearing"], "bom": f["bom"]}, None, f"qa-smoke c{k}"))
                        for u in users for k in range(2)]
                for u, fu in futs:
                    subs.append((u, fu.result()[1]))
            states_at_submit = [j["state"] for _, j in subs]
            done = [self.wait(u, j["id"]) for u, j in subs]
            ok = all(d["state"] == "SUCCEEDED" and [x["rule_id"] for x in d["findings"]] == ["BEARING_SEAT"]
                     for d in done)
            self.record("6 concurrent jobs from 3 users (1 at a time each on free)", ok and "QUEUED" in states_at_submit,
                        {"at_submit": states_at_submit, "final": [d["state"] for d in done]})

        def duplicate():
            code, up = self.upload("qa-smoke-u3", {"step": f["motor"]})
            hdr = self.h("qa-smoke-u3") | {"Idempotency-Key": "qa-dup-" + up["upload_id"]}
            a = self.http.post(f"{self.base}/api/analysis", headers=hdr, json={"upload_id": up["upload_id"]}).json()
            b = self.http.post(f"{self.base}/api/analysis", headers=hdr, json={"upload_id": up["upload_id"]}).json()
            j = self.wait("qa-smoke-u3", a["id"])
            self.record("duplicate submission -> one job, one run", a["id"] == b["id"] and j["attempts"] == 1,
                        {"same_id": a["id"] == b["id"], "attempts": j["attempts"]})

        def quota():
            c1, j1 = self.submit("qa-smoke-quota", {"step": f["motor"]})
            c2, j2 = self.submit("qa-smoke-quota", {"step": f["motor"]})
            if c1 == 202:
                self.wait("qa-smoke-quota", j1["id"])
            self.record("daily quota -> 429 on the second job", c1 in (202, 429) and c2 == 429, {"first": c1, "second": c2})
            plans = {u: self.http.get(f"{self.base}/api/analysis", headers=self.h(u)).json()[:1]
                     for u in ("qa-smoke-u1", "qa-smoke-memory")}
            got = {u: (v[0]["plan"] if v else None) for u, v in plans.items()}
            self.record("plan decided server-side", got == {"qa-smoke-u1": "free", "qa-smoke-memory": "qa_memory"}, got)

        def crash():
            from create_cad_secret import build as secret_build
            import modal
            import sqlalchemy as sa
            code, job = self.submit("qa-smoke-pro", {"step": f["mesh"]}, label="qa-smoke crash")
            eng = sa.create_engine(secret_build(self.env, "x")["IC_DATABASE_URL"])
            ref, t0 = None, time.time()
            while time.time() - t0 < 300:
                with eng.connect() as c:
                    row = c.execute(sa.text("select state, dispatch_ref from analysis_jobs where id=:i"),
                                    {"i": job["id"]}).first()
                if row and row[0] == "RUNNING" and row[1]:
                    ref = row[1]
                    break
                time.sleep(0.5)
            if ref is None:
                raise RuntimeError("job never reached RUNNING")
            modal.FunctionCall.from_id(ref).cancel(terminate_containers=True)   # the container dies mid-job
            j = self.wait("qa-smoke-pro", job["id"], timeout=900)
            with eng.connect() as c:
                runs = [tuple(r) for r in c.execute(sa.text(
                    "select attempt, tier, outcome, failure_code from worker_runs where job_id=:i order by id"),
                    {"i": job["id"]})]
            self.record("worker crash -> recovered and retried", j["state"] == "SUCCEEDED" and j["attempts"] == 2
                        and any(r[2] == "LOST" for r in runs), {"state": j["state"], "attempts": j["attempts"], "runs": runs})

        def rls():
            from create_cad_secret import build as secret_build
            import sqlalchemy as sa
            eng = sa.create_engine(secret_build(self.env, "x")["IC_DATABASE_URL"])
            with eng.connect() as c:
                total = c.execute(sa.text("select count(*) from analysis_jobs")).scalar()
            seen = {}
            for role in ("anon", "authenticated"):
                with eng.connect() as c:
                    c.execute(sa.text(f"set local role {role}"))        # lasts until this transaction ends
                    seen[role] = c.execute(sa.text("select count(*) from analysis_jobs")).scalar()
                    c.rollback()
            self.record("RLS: anon/authenticated see no rows", total > 0 and all(v == 0 for v in seen.values()),
                        {"rows": total, **seen})

        # the memory-limit job runs at the same time as other users' jobs: isolation under failure
        with ThreadPoolExecutor(8) as ex:
            futs = [ex.submit(self.run_case, n, fn) for n, fn in [
                ("normal", normal), ("oversized", oversized), ("corrupt", corrupt), ("mesh", mesh),
                ("timeout", timeout), ("memory", memory), ("concurrent", concurrent), ("duplicate", duplicate)]]
            for fu in futs:
                fu.result()
        health = self.http.get(f"{self.base}/api/health")
        self.record("API healthy after the failure cases", health.status_code == 200, health.json())
        self.run_case("quota", quota)
        self.run_case("crash", crash)
        self.run_case("rls", rls)
        metrics = self.http.get(f"{self.base}/api/admin/metrics", params={"days": 1},
                                headers=self.h(self.env.get("SMOKE_ADMIN", "ad698ec0-f469-4c0d-9377-c89f638257b2")))
        return {"base": self.base, "wall_s": round(time.time() - t_all, 1),
                "passed": sum(r["ok"] for r in self.results), "total": len(self.results),
                "results": self.results, "jobs": self.jobs,
                "metrics": metrics.json() if metrics.status_code == 200 else metrics.text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default="smoke_interface_check.json")
    ap.add_argument("--work", default=None)
    a = ap.parse_args()
    import tempfile
    work = Path(a.work or tempfile.mkdtemp(prefix="ic-smoke-"))
    res = Smoke(a.base, work).run()
    Path(a.out).write_text(json.dumps(res, indent=2, default=str))
    print(f"\n{res['passed']}/{res['total']} passed in {res['wall_s']} s -> {a.out}")


if __name__ == "__main__":
    main()
