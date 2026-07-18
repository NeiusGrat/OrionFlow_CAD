"""Push deploy/.env.deploy into a Modal secret named 'orionflow-secrets'.

Usage:
    python deploy/create_modal_secret.py                # fail if TODOs remain
    python deploy/create_modal_secret.py --skip-missing # omit TODO keys for now

Only whitelisted runtime keys are pushed; anything else in the file
(notes, Supabase dashboard extras) is ignored.
"""

import os
import re
import subprocess
import sys

KEYS = [
    "ENVIRONMENT",
    "DEBUG",
    "LLM_PROVIDER",
    "OFL_LLM_PROVIDER",
    "OFL_LLM_FALLBACK_PROVIDER",
    "GROQ_API_KEY",
    "K2THINK_API_KEY",
    "K2THINK_BASE_URL",
    "JWT_SECRET_KEY",
    "GOOGLE_CLIENT_ID",
    "CORS_ORIGINS",
    "FRONTEND_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "DB_SSL",
    "S3_BUCKET",
    "S3_ENDPOINT_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
]

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env.deploy")

env: dict[str, str] = {}
for line in open(ENV_FILE):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
    if m and m.group(1) in KEYS:
        env[m.group(1)] = m.group(2)

todo = sorted(k for k, v in env.items() if "TODO" in v or "YOUR-" in v or v.startswith("<"))
if todo:
    if "--skip-missing" in sys.argv:
        print(f"NOTE: deploying WITHOUT {', '.join(todo)} — related features degraded")
        for k in todo:
            env.pop(k)
    else:
        sys.exit(f"Fill these in {ENV_FILE} first: {', '.join(todo)}")

cmd = [sys.executable, "-m", "modal", "secret", "create", "orionflow-secrets", "--force"]
cmd += [f"{k}={v}" for k, v in env.items()]
result = subprocess.run(cmd)
print(f"pushed {len(env)} keys to Modal secret 'orionflow-secrets'")
sys.exit(result.returncode)
