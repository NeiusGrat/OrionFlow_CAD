"""OrionFlow CAD analysis on Modal: a stateless API and one worker class per tier.

Deploy:   python -m modal deploy deploy/modal_interface_check.py
Secret:   Modal secret "orionflow-cad-secrets" holding
            IC_DATABASE_URL      postgresql+psycopg://...:6543/...  (Supabase TRANSACTION pooler;
                                 session mode on 5432 caps all clients at 15)
            IC_S3_BUCKET         private bucket for jobs/ and cache/
            IC_S3_ENDPOINT       https://<project>.supabase.co/storage/v1/s3
            IC_S3_REGION         the project's region
            IC_S3_KEY / IC_S3_SECRET   Supabase Storage S3 access keys
            IC_JWT_SECRET        the main API's JWT secret (app.orionflow.in tokens work as-is)
            IC_ADMIN_USERS       user ids allowed to read /api/admin/metrics and /api/health/deep
            IC_PLAN_OVERRIDES    optional "user_id=plan,..." for pilots before billing has them
            IC_EXTRA_PLANS       optional operator-defined plans (JSON), e.g. QA plans
            INTERFACE_CHECK_LLM_URL / _KEY / _MODEL   optional, the reasoning layer

    web          1 CPU / 1 GB, many requests per container, scales out. Never
                 touches geometry: it signs uploads, validates, records, and
                 calls ``cad_<tier>.spawn``.
    cad_small    4 CPU /  8 GB  \
    cad_medium   8 CPU / 16 GB   |  one job per container (no input concurrency),
    cad_large   16 CPU / 32 GB   |  each job in an isolated child process under a
    cad_extreme 32 CPU / 64 GB  /   memory + time watchdog. Containers exit idle.
    maintenance  every minute: recover jobs whose worker vanished, pump the
                 queue, delete jobs past retention.

``max_containers`` per tier is the infrastructure cost ceiling; plan limits
(per-user concurrency, daily jobs, monthly compute) are enforced by the API
before anything is spawned. Tier sizes are starting points: retune them from
``/api/admin/metrics`` (peak memory by tier) once real jobs run.
"""

import subprocess

import modal


def _build_stamp() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "interface_check"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else "unknown"
    except Exception:  # noqa: BLE001 - a deploy from a tarball has no git
        return "unknown"


APP = "orionflow-cad"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0", "libxrender1")
    # The geometry kernel is pinned to the versions the engine is tested with:
    # OCP 7.9 moved XCAF label classes and the STEP reader fails to import.
    .pip_install("build123d==0.10.0", "cadquery-ocp==7.8.1.1.post1", "numpy", "trimesh==4.11.0",
                 "rapidfuzz", "pymupdf>=1.24", "pyyaml", "httpx", "fastapi", "python-multipart", "pydantic>=2",
                 "sqlalchemy>=2", "psycopg[binary]>=3.1", "boto3", "psutil", "pyjwt")
    .env({
        "IC_DISPATCH": "modal", "IC_STORAGE": "s3", "IC_MODAL_APP": APP, "IC_WORK_ROOT": "/tmp",
        "IC_RETENTION_DAYS": "30", "IC_GLOBAL_CONCURRENCY": "50",
        "INTERFACE_CHECK_CACHE": "/tmp/llm-cache", "INTERFACE_CHECK_BUILD": _build_stamp(),
    })
    .add_local_dir("interface_check", "/root/interface_check", copy=True,
                   ignore=["**/__pycache__", "**/*.pyc", "tests/**"])
    # The SKF bearing table is read where it lives, not copied into the package.
    .add_local_file("orion/knowledge/skf_deep_groove.json", "/root/orion/knowledge/skf_deep_groove.json",
                    copy=True)
)

app = modal.App(APP, image=image)
secrets = [modal.Secret.from_name("orionflow-cad-secrets")]

#: tier -> (cpu, memory MiB, max containers). Runtime ceiling is the largest plan's + slack.
TIERS = {"small": (4, 8192, 20), "medium": (8, 16384, 10), "large": (16, 32768, 4), "extreme": (32, 65536, 2)}
WORKER_TIMEOUT_S = 7200 + 600


def _run(job_id: str, tier: str) -> str:
    import json
    import os
    import sys
    sys.path.insert(0, "/root")
    os.environ.setdefault("IC_DB_POOL_SIZE", "1")      # a worker needs one connection at a time
    os.environ.setdefault("IC_DB_MAX_OVERFLOW", "1")
    if job_id == "__probe__":                          # deep health check: no job, no database
        from interface_check.service.worker import probe
        return json.dumps({**probe(), "tier": tier})
    from interface_check.service.dispatch import context
    from interface_check.service.worker import execute_job
    return execute_job(job_id, context(), tier)


@app.function(secrets=secrets, cpu=TIERS["small"][0], memory=TIERS["small"][1],
              max_containers=TIERS["small"][2], timeout=WORKER_TIMEOUT_S, scaledown_window=60)
def cad_small(job_id: str, tier: str = "SMALL") -> str:
    return _run(job_id, tier)


@app.function(secrets=secrets, cpu=TIERS["medium"][0], memory=TIERS["medium"][1],
              max_containers=TIERS["medium"][2], timeout=WORKER_TIMEOUT_S, scaledown_window=60)
def cad_medium(job_id: str, tier: str = "MEDIUM") -> str:
    return _run(job_id, tier)


@app.function(secrets=secrets, cpu=TIERS["large"][0], memory=TIERS["large"][1],
              max_containers=TIERS["large"][2], timeout=WORKER_TIMEOUT_S, scaledown_window=60)
def cad_large(job_id: str, tier: str = "LARGE") -> str:
    return _run(job_id, tier)


@app.function(secrets=secrets, cpu=TIERS["extreme"][0], memory=TIERS["extreme"][1],
              max_containers=TIERS["extreme"][2], timeout=WORKER_TIMEOUT_S, scaledown_window=60)
def cad_extreme(job_id: str, tier: str = "EXTREME") -> str:
    return _run(job_id, tier)


@app.function(secrets=secrets, cpu=1, memory=1024, schedule=modal.Period(minutes=1), timeout=300)
def maintenance() -> dict:
    import os
    import sys
    sys.path.insert(0, "/root")
    os.environ.setdefault("IC_DB_POOL_SIZE", "1")
    os.environ.setdefault("IC_DB_MAX_OVERFLOW", "1")
    from interface_check.service.api import run_maintenance
    return run_maintenance()


@app.function(secrets=secrets, cpu=1, memory=1024, min_containers=0, max_containers=10, scaledown_window=300)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os
    import sys

    sys.path.insert(0, "/root")
    if not os.environ.get("IC_JWT_SECRET"):
        raise RuntimeError("refusing to serve customer CAD without IC_JWT_SECRET")
    if os.environ.get("IC_DEV_TOKEN"):
        raise RuntimeError("IC_DEV_TOKEN must never be set on a hosted deployment")
    if os.environ.get("IC_STORAGE") != "s3" or not os.environ.get("IC_DATABASE_URL", "").startswith("postgresql"):
        raise RuntimeError("hosted deployment requires S3-compatible storage and Postgres, never local files")
    from interface_check.service.api import app as api

    @api.get("/api/version")
    def version() -> dict:
        return {"build": os.environ.get("INTERFACE_CHECK_BUILD", "unknown")}

    # The OrionFlow web app calls this service from the browser. CORS lives here, in
    # the hosted wrapper, not in api.py: mounted inside the main API (/verify) the
    # main app's own CORS middleware already answers, and two would double headers.
    from fastapi.middleware.cors import CORSMiddleware

    origins = [o.strip() for o in os.environ.get(
        "IC_CORS_ORIGINS", "https://app.orionflow.in,https://orionflow.in,http://localhost:5173").split(",") if o.strip()]
    api.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    return api
