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
    # Our own fine-tuned model, served from the MI300X, plus the fallback it
    # is allowed to drop to. The studio reads these via
    # orion_agent/shared/config.py.
    "ORION_LLM_PROVIDER",
    "ORION_LLM_MODEL",
    "ORION_LLM_BASE_URL",
    "ORION_LLM_API_KEY",
    "ORION_LLM_FALLBACK_PROVIDER",
    # Blueprints are long; the default token budget truncates them mid-JSON.
    "ORION_LLM_MAX_TOKENS",
    "ORION_LLM_TEMPERATURE",
    "ORION_LLM_TIMEOUT",
    # FreeCAD is not in the API image; Blueprint builds go to the separate
    # orionflow-builder Modal app.
    "ORION_BUILDER_MODE",
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

# One remotely served OrionFlow model backs both the studio and the desktop
# copilot. Without an endpoint the deployed service has no model at all, so this
# is a deploy-time failure rather than a runtime surprise.
REQUIRED = ["ORION_LLM_PROVIDER", "ORION_LLM_MODEL", "ORION_LLM_BASE_URL"]

missing = [k for k in REQUIRED if not env.get(k, "").strip()]
if missing:
    sys.exit(f"Set these in {ENV_FILE} before deploying: {', '.join(missing)}\n"
             "ORION_LLM_BASE_URL is the remotely served OrionFlow endpoint.")

# A localhost endpoint in a Modal secret points the container at itself. It
# fails as "the model is unreachable", which sends you debugging the model
# rather than the address.
endpoint = env["ORION_LLM_BASE_URL"]
if any(host in endpoint for host in ("127.0.0.1", "localhost", "0.0.0.0")):
    sys.exit(f"ORION_LLM_BASE_URL is {endpoint!r} — that is a local address and "
             "resolves to the Modal container itself. Use the remotely served "
             "endpoint for production; keep localhost in your own .env only.")

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
