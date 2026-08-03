"""OrionFlow API on Modal (free Starter tier: $30/mo credits, scale-to-zero).

Deploy:   modal deploy deploy/modal_app.py
Secrets:  expects a Modal secret named "orionflow-secrets" holding the
          production env (GROQ_API_KEY, JWT_SECRET_KEY, DB_*, CORS_ORIGINS,
          S3_*/AWS_* ...) — created by deploy/create_modal_secret.py.

The served URL is https://<workspace>--orionflow-api-api.modal.run
"""

import subprocess

import modal


def _build_stamp() -> str:
    """A string that changes whenever the code *in the image* does.

    Exposed on ``GET /health`` as ``build`` so "did my deploy actually take?"
    is one request rather than an inspection of the OpenAPI schema. A dirty
    tree is marked, because the commit alone would then be a lie about what is
    running.

    Scoped by **path** to what is actually baked into the image, which is the
    whole point of the flag rather than a refinement of it. ``git status
    --porcelain`` over the entire tree reports untracked notes, scratch data and
    downloaded datasets sitting at the repo root — none of which enter the image
    — so production reported ``-dirty`` while the code it served was exactly the
    commit. A marker that is always on tells you nothing, and the one time it
    matters you have already learned to ignore it.

    Untracked files *inside* those paths still count, and deliberately so: a new
    module under ``app/`` has never been committed but is copied into the image
    all the same, so the running code really does differ from the commit. Adding
    ``--untracked-files=no`` would scope this by the wrong axis and hide exactly
    the case the flag exists for.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--"]
            + _SOURCE_DIRS + ["requirements.txt", "alembic.ini"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else "unknown"
    except Exception:  # noqa: BLE001 - a deploy from a tarball has no git
        return "unknown"


#: Source directories baked into the image.
#:
#: ``copy=True`` is load-bearing, not a preference. With the default
#: ``copy=False`` these are *runtime mounts*: their contents never enter the
#: image definition, so editing ``app/`` leaves the image ID unchanged. That is
#: normally just a speed optimisation — but combined with
#: ``enable_memory_snapshot=True`` below it silently serves stale code, because
#: the snapshot is keyed on the image and restores a process that already
#: imported the *old* modules. A deploy then reports success while the new
#: routes do not exist. That happened on 2026-08-01: ``/studio/rebuild``
#: 404'd through two consecutive "successful" deploys and only appeared after
#: `modal app stop` forced fresh containers.
#:
#: With ``copy=True`` the file contents are hashed into an image layer, so any
#: source change produces a new image, which invalidates the snapshot. Deploys
#: that change code are slower by one small layer rebuild. That is the price of
#: a deploy meaning what it says.
_SOURCE_DIRS = [
    "app",
    "orionflow_ofl",
    "orion_physical_ai",
    # The studio path needs both: `orion` for the Blueprint contract and its
    # assertion checker, `orion_agent` for the LLM client and config. Neither
    # pulls FreeCAD in at import time — the build itself goes to the separate
    # builder app — so this stays cheap.
    "orion",
    "orion_agent",
    "alembic",
]

image = (
    modal.Image.debian_slim(python_version="3.11")
    # libgl1/libglu1/libxrender1/libxext6: required by the OCP (OpenCascade)
    # wheel that build123d links against; absent on slim images.
    .apt_install("libgl1", "libglu1-mesa", "libxrender1", "libxext6", "libpq5")
    .pip_install_from_requirements("requirements.txt")
    .env(
        {
            "PYTHONPATH": "/root",
            "ENVIRONMENT": "production",
            "DEBUG": "false",
            # Belt and braces behind copy=True: pins the image to the commit, so
            # even a change this file forgot to copy still gets a fresh snapshot.
            "ORIONFLOW_BUILD": _build_stamp(),
        }
    )
)

for _d in _SOURCE_DIRS:
    # Bytecode caches carry no information and would churn the layer hash on
    # every deploy, forcing a rebuild when nothing actually changed.
    image = image.add_local_dir(
        _d, f"/root/{_d}", copy=True, ignore=["**/__pycache__", "**/*.pyc"]
    )

image = image.add_local_file("alembic.ini", "/root/alembic.ini", copy=True)

app = modal.App("orionflow-api")

# Import the FastAPI app at container-import time so the memory snapshot
# captures it.
#
# This used to drag in OCP/OpenCascade — 542 modules, and the whole reason the
# snapshot below exists. It no longer does: build123d is behind a lazy import
# (see app/services/generation_service.py) because no live route uses it, and
# `import app.main` now costs seconds rather than minutes. The snapshot is still
# worth keeping — it also captures the FastAPI app, the SQLAlchemy metadata and
# the pydantic model builds — but it is no longer hiding a two-minute import.
#
# tests/test_one_canonical_ir.py asserts this stays true.
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
