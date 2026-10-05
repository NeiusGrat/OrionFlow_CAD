"""Build the Modal secret "orionflow-cad-secrets" from deploy/.env.deploy.

Usage:
    python deploy/create_cad_secret.py --admin <user-uuid>[,<user-uuid>]

Reads the same deploy/.env.deploy the main API's secret comes from, maps it
onto the IC_* names the CAD analysis service reads, and hands it to the Modal
CLI through a temporary JSON file that is deleted immediately. No value is
printed or passed on a command line.

QA accounts (sub = "qa-...") are put on QA-only plans with tiny limits so the
production smoke test can exercise timeouts, memory limits and quotas without
changing any real user's limits.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote_plus

ENV = Path(__file__).with_name(".env.deploy")
BUCKET = "orionflow-cad"
K2_BASE = "https://api.ifm.ai/v1"
K2_MODEL = "IFM/K2-Horizon-375B-A23B"      # host and model id are a matched pair
TXN_POOLER_PORT = 6543

QA_PLANS = {
    "qa_timeout": {"base": "pro", "max_runtime_s": 3},
    "qa_memory": {"base": "pro", "max_memory_mb": 150},
    "qa_quota": {"base": "free", "daily_jobs": 1},
}
QA_USERS = {"qa-smoke-pro": "pro", "qa-smoke-timeout": "qa_timeout", "qa-smoke-memory": "qa_memory",
            "qa-smoke-quota": "qa_quota"}


def load(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build(e: dict, admins: str) -> dict:
    need = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME", "S3_ENDPOINT_URL", "AWS_REGION",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "JWT_SECRET_KEY"]
    missing = [k for k in need if not e.get(k) or "TODO" in e[k]]
    if missing:
        sys.exit(f"missing in {ENV.name}: {', '.join(missing)}")
    s = {
        # Transaction-mode pooler (6543), not session mode (5432): session mode caps
        # every client together at 15 connections, which a few workers exhaust.
        "IC_DATABASE_URL": (f"postgresql+psycopg://{quote_plus(e['DB_USER'])}:{quote_plus(e['DB_PASSWORD'])}"
                            f"@{e['DB_HOST']}:{TXN_POOLER_PORT}/{e['DB_NAME']}?sslmode=require"),
        "IC_S3_BUCKET": BUCKET, "IC_S3_ENDPOINT": e["S3_ENDPOINT_URL"], "IC_S3_REGION": e["AWS_REGION"],
        "IC_S3_KEY": e["AWS_ACCESS_KEY_ID"], "IC_S3_SECRET": e["AWS_SECRET_ACCESS_KEY"],
        "IC_JWT_SECRET": e["JWT_SECRET_KEY"], "IC_JWT_ALG": "HS256",
        "IC_ADMIN_USERS": admins,
        "IC_EXTRA_PLANS": json.dumps(QA_PLANS),
        "IC_PLAN_OVERRIDES": ",".join(f"{u}={p}" for u, p in QA_USERS.items()),
    }
    if e.get("K2THINK_API_KEY"):
        s.update({"INTERFACE_CHECK_LLM_URL": K2_BASE, "INTERFACE_CHECK_LLM_KEY": e["K2THINK_API_KEY"],
                  "INTERFACE_CHECK_LLM_MODEL": K2_MODEL})
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", required=True, help="comma-separated user ids with admin access")
    ap.add_argument("--name", default="orionflow-cad-secrets")
    a = ap.parse_args()
    secret = build(load(ENV), a.admin)
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(secret, fh)
        r = subprocess.run([sys.executable, "-m", "modal", "secret", "create", a.name, "--from-json", tmp, "--force"],
                           capture_output=True, text=True)
    finally:
        os.unlink(tmp)
    if r.returncode != 0:
        sys.exit(f"modal secret create failed: {r.stderr[-500:]}")
    print(f"{a.name}: {', '.join(sorted(secret))}")


if __name__ == "__main__":
    main()
