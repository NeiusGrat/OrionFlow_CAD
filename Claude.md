# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Repository map
- `app/`: FastAPI backend. Routers live in `app/main.py`, delegating to service-layer orchestration in `app/services`.
- `orionflow-ui/`: Vite + React front-end that calls the backend (dev server origin `http://localhost:5173` is pre-whitelisted in CORS).
- `tests/`: Pytest suite covering compilers, dataset plumbing, context engine, retry policy, etc.
- `outputs/`: Local export target for generated `*.glb`, `*.stl`, and `*.step` files (must exist or be created before running jobs).

## Environment & prerequisites
- Python 3.10+ with `pip`. Create a virtualenv and install `pip install -r requirements.txt`. Key services rely on `fastapi`, `build123d`, `trimesh`, `groq`, and `numpy`.
- Node 20+ for the UI (`cd orionflow-ui && npm install`).
- Required env vars:
  - `GROQ_API_KEY` (LLMClient uses it to call `llama-3.3-70b-versatile` via Groq).
  - Optional Onshape sync: `ONSHAPE_DOC_ID`, `ONSHAPE_WORKSPACE_ID`, `ONSHAPE_ELEMENT_ID`.
  - `.env` is loaded automatically by `app/main.py`.

## Common commands
### Backend
- Install deps: `python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt`
- Run API with hot reload: `uvicorn app.main:app --reload`
- Run full test suite: `pytest`
- Run a single test: `pytest tests/test_context_engine.py -k reference`
- Lint/type hints are not centralized; rely on Pyright/mypy if added later.

### Frontend (inside `orionflow-ui/`)
- Install deps: `npm install`
- Start dev server: `npm run dev` (listens on 5173)
- Build bundle: `npm run build`
- Lint: `npm run lint`

## Architecture highlights
### FastAPI surface
- `app/main.py` exposes `/generate`, `/regenerate`, `/describe`, and file download endpoints. It mounts `outputs/` for static delivery and enforces a CORS origin for the Vite dev server.

### Generation pipeline (core backend)
1. `GenerationService.generate()` orchestrates the unified V2 pipeline:
   - Decomposes prompts into `DecomposedIntent` (filters unsupported operations early).
   - Calls `LLMClient.generate_feature_graph()` to obtain a strict `FeatureGraphV1`.
   - Compiles graphs with `FeatureGraphCompilerV1` (Build123d backend) or delegates to Onshape if configured.
   - Exports GLB/STEP/STL via `build123d` and logs dataset samples (`app/services/dataset_writer.py`) plus retry traces.
2. `GenerationService.regenerate()` recompiles edited feature graphs, re-syncing to Onshape when credentials are present and logging feedback for active learning.
3. `app/services/retry_policy.py` flags retryable compiler failures so the service can re-prompt the LLM.

### Conversational + context subsystems
- `app/services/conversational_editor.py` tries heuristic parameter edits first, then falls back to LLM-guided edits using a strict prompt template.
- `app/context/context_engine.py` tracks session state (conversation history, active topology references, parameter history) to resolve phrases like “that edge” during multi-turn interactions.

### Domain models & compilers
- `app/domain/feature_graph_v1.py` (not shown above) represents canonical CFG v1. `feature_graph_v2.py` introduces semantic topology selectors for advanced operations; `app/compilers/build123d_compiler_v2.py` demonstrates V2 support with selector resolution and filter chains.
- `app/domain/generation_result.py` standardizes outputs across v1/v2 and carries execution traces for retries/analytics.
- `app/cad/onshape/` and `app/clients/onshape_client.py` (when configured) adapt graphs to FeatureScript and push to cloud workspaces.

### LLM integration
- `app/llm/client.py` abstracts provider-specific logic (currently Groq). It enforces JSON-only responses, performs auto-repair, and validates outputs through Pydantic schemas before the compiler sees them. The retry prompt (`app/llm/prompts.py`) includes execution traces to steer the model after failures.

### Dataset & validation support
- `app/services/dataset_writer.py` and `app/domain/dataset_sample.py` persist prompt/graph/trace tuples for offline learning.
- `app/validation/` and `app/services/retry_policy.py` encapsulate guardrails (sanity checks, error recovery).
- Standalone scripts like `generate_part.py`, `check_build123d.py`, and `debug_trace.py` help reproduce compiler issues.

### Frontend (orionflow-ui)
- Vite + React + TypeScript. Scripts in `package.json` handle dev/build/lint. Components are expected to call backend endpoints at `http://localhost:8000` (configure proxies if necessary). CORS in FastAPI currently allows only `http://localhost:5173`, so adjust `app/main.py` when hosting elsewhere.

## Testing guidance
- Python tests use Pytest (`tests/` directory). Coverage spans compilers (`tests/test_compiler_v1.py`), constraints, retry policy, dataset ingestion, context engine, and LLM prompt handling. When debugging a failing scenario, run `pytest tests/test_feature_graph_v2.py -vv` for detailed traces.
- For quick backend smoke tests after code changes, issue a sample prompt via HTTP: `curl -X POST http://127.0.0.1:8000/generate -H "Content-Type: application/json" -d "{\"prompt\":\"Create a 20mm tall cylinder\"}"`. Geometry files will appear in `outputs/`.

## Operational tips
- Ensure `outputs/` exists and is writable; both FastAPI static serving and exporters assume it.
- `GenerationService` logs dataset samples even on failures—monitor the log output to avoid unbounded growth (rotate `data/` periodically).
- If Onshape credentials are absent, the service silently degrades to local Build123d. When debugging cloud sync, enable WARN/INFO logs for `app.services.generation_service`.

