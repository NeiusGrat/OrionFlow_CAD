"""OrionFlow API on Modal (free Starter tier: $30/mo credits, scale-to-zero).

Deploy:   modal deploy deploy/modal_app.py
Secrets:  expects a Modal secret named "orionflow-secrets" holding the
          production env (GROQ_API_KEY, JWT_SECRET_KEY, DB_*, CORS_ORIGINS,
          S3_*/AWS_* ...) — created by deploy/create_modal_secret.py.

The served URL is https://<workspace>--orionflow-api-api.modal.run
"""

import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    # libgl1/libglu1/libxrender1/libxext6: required by the OCP (OpenCascade)
    # wheel that build123d links against; absent on slim images.
    .apt_install("libgl1", "libglu1-mesa", "libxrender1", "libxext6", "libpq5")
    .pip_install_from_requirements("requirements.txt")
    .env({"PYTHONPATH": "/root", "ENVIRONMENT": "production", "DEBUG": "false"})
    .add_local_dir("app", "/root/app")
    .add_local_dir("orionflow_ofl", "/root/orionflow_ofl")
    .add_local_dir("alembic", "/root/alembic")
    .add_local_file("alembic.ini", "/root/alembic.ini")
)

app = modal.App("orionflow-api")

# Import the FastAPI app (and with it OCP/OpenCascade, the ~2-min cold-boot
# cost) at container-import time so the memory snapshot captures it.
with image.imports():
    from app.main import app as fastapi_app


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("orionflow-secrets")],
    cpu=2,
    memory=2048,
    timeout=300,
    scaledown_window=600,  # keep a warm container 10 min after last request
    min_containers=0,  # scale to zero — stays inside the $30/mo credits
    # Cold boot was ~2 min (OCP/OpenCascade import). Snapshot captures the
    # imported process image; later cold starts restore it in seconds. The
    # asyncpg engine is created lazily (no open sockets at snapshot time) and
    # migrations run in a subprocess that exits, so the state is snapshot-safe.
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=20)  # FastAPI is async; share the container
@modal.asgi_app()
def api():
    import subprocess

    # Modal has no release phase; run idempotent migrations at container boot.
    # Lenient: the LLM->geometry endpoints work even if the DB is unreachable.
    result = subprocess.run(
        ["alembic", "upgrade", "head"], cwd="/root", capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"WARNING: migrations failed, auth degraded: {result.stderr[-500:]}")

    return fastapi_app
