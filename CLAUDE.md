# OrionFlow CAD

AI-powered text-to-CAD. FastAPI service that turns natural-language prompts into parametric build123d models and exports STEP/STL/GLB.

## Layout

- `app/` — FastAPI service (entry: `app/main.py`)
  - `api/v1/` — versioned REST routes (auth, users, designs, billing, jobs)
  - `cad/` — CAD helpers, validators, Onshape integration, `describe.py`
  - `compilers/` — FeatureGraph → geometry. `build123d_compiler.py` (v1), `_v2`, `_v3`. v3 is gated by `settings.use_v3_compiler`. `onshape_compiler.py` for cloud backend.
  - `domain/feature_graph.py` — `FeatureGraph` Pydantic model (the IR between LLM and compiler)
  - `llm/` — LLM client + prompts (Groq). `prompts.py` and `prompts_v2.py`.
  - `services/generation_service.py` — orchestrates prompt → graph → geometry
  - `intent/`, `context/`, `validation/`, `middleware/`, `db/`, `auth/`, `billing/`, `workers/` (Celery)
- `orionflow_ofl/` — OrionFlow Language (OFL), a deterministic Python CAD DSL built on build123d
  - Public API: `Plane`, `Sketch`, `Part`, `Hole`, `export` (see `orionflow_ofl/__init__.py`)
  - `data_pipeline/` — dataset generation for fine-tuning (DeepCAD converter, synthetic templates, text annotator, validator, dataset builder)
  - `ir/exporter.py` — AST-based IR exporter (offline)
  - Isolated from `app/`; has its own tests
- `tests/` — main test suite (316 tests, `pytest tests/`)
- `orionflow_ofl/tests/` — OFL core tests (5)
- `orionflow_ofl/data_pipeline/tests/` — pipeline tests (28)
- `scripts/` — dataset + validation scripts (`run_full_validation.py`, `validate_all_templates.py`, `merge_final.py`, ...)
- `fine_tuning/`, `data/`, `outputs/`, `archive/` — datasets, runtime outputs, archived experiments
- `orionflow-ui/` — frontend (separate npm project)
- `alembic/` — DB migrations
- `docker/`, `docker-compose*.yml`, `Dockerfile`, `Makefile`

## Commands

Windows + bash shell. Use forward slashes; don't `cd /d`. Python 3.11.5 (Anaconda).

```bash
# Dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Tests
pytest tests/                                  # main suite (316)
pytest orionflow_ofl/tests/                    # OFL core (5)
pytest orionflow_ofl/data_pipeline/tests/      # pipeline (28)
pytest tests/ -v -m "not integration"          # unit only

# Lint / format
ruff check app/ tests/
black app/ tests/
mypy app/ --ignore-missing-imports

# DB
alembic upgrade head
alembic revision --autogenerate -m "msg"

# Docker
docker-compose -f docker-compose.dev.yml up --build
```

`pytest.ini` has `testpaths = tests` — OFL suites must be invoked explicitly with their path. No `pytest-timeout` installed.

## Core Flow

1. `POST /generate` → `GenerationService.generate(prompt, backend)`
2. LLM client (`app/llm/client.py`) produces a `FeatureGraph`
3. Compiler (`app/compilers/build123d_compiler*.py`) builds geometry
4. Exports STEP/STL/GLB into `settings.output_dir`, served under `/outputs`
5. `POST /regenerate` re-compiles an edited `FeatureGraph` without hitting the LLM; optional conversational edit via `ConversationalEditor`

`FeatureGraph` is the single source of truth between LLM and compiler — changes there ripple through both sides.

## Dependencies

Python: fastapi, uvicorn, pydantic, pydantic-settings, **build123d>=0.5.0**, trimesh, numpy, groq, structlog, pytest. Optional: ocp-vscode, redis, sentry, prometheus_client, celery, alembic, sqlalchemy.

## build123d gotchas (confirmed working)

- `RectangleRounded(width, height, radius)` exists.
- `Pos(x, y, z) * Cylinder(radius, height)` for positioning; cylinder is centered at origin, extends `-h/2..+h/2` on Z.
- `BuildPart.part` → `build123d.topology.composite.Part`.
- Boolean `solid - cyl` returns a `Compound`, still exportable.
- `solid.bounding_box().min.Z` / `.max.Z` for extents.
- `max(solid.faces(), key=lambda f: f.center().Z)` for top face.
- `export_step(shape, str_path)` / `export_stl(shape, str_path)`.

## Conventions

- Structured logging via `app/logging_config.py` (`structlog`). Request IDs are set per-request in `app/main.py`.
- Errors: raise `OrionFlowError` subclasses from `app/exceptions.py`; the global handler in `main.py` converts them to JSON.
- Settings: centralized in `app/config.py` via `pydantic-settings`. Feature flags: `use_v3_compiler`, `use_two_stage_pipeline`.
- `orionflow_ofl` is deliberately isolated from `app/` — do not import `app.*` from inside `orionflow_ofl/`.
- Subprocess validation in the data pipeline injects `PYTHONPATH` so `orionflow_ofl` is importable.
- Run the full `tests/` suite after non-trivial changes to catch regressions.
