# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Repository map
- `app/`: FastAPI backend. Routers live in `app/main.py`, delegating to service-layer orchestration in `app/services`.
- `app/config.py`: **Centralized configuration** using Pydantic BaseSettings. All settings are loaded from `.env`.
- `orionflow-ui/`: Vite + React front-end that calls the backend (dev server origin `http://localhost:5173` is pre-whitelisted in CORS).
- `tests/`: Pytest suite covering compilers, dataset plumbing, context engine, retry policy, etc.
- `outputs/`: Local export target for generated `*.glb`, `*.stl`, and `*.step` files (auto-created if missing).

## Quick Start

### 1. Clone & Setup Environment
```bash
# Clone repository
git clone https://github.com/sahilmaniyar888/OrionFlow_CAD.git
cd OrionFlow_CAD

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
# Copy example configuration
cp .env.example .env

# Edit .env and add your API keys
# REQUIRED: GROQ_API_KEY for LLM-based CAD generation
```

**Key environment variables:**
| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ Yes | Groq API key for LLM access |
| `LLM_MODEL` | No | LLM model (default: `llama-3.3-70b-versatile`) |
| `OUTPUT_DIR` | No | Output directory (default: `outputs`) |
| `MAX_LLM_RETRIES` | No | Retry attempts on failure (default: `1`) |
| `CORS_ORIGINS` | No | Allowed CORS origins (default: `http://localhost:5173`) |
| `DEBUG` | No | Enable debug mode (default: `false`) |

See `.env.example` for full list of configuration options.

### 3. Run the Application
```bash
# Start backend API (with hot reload)
uvicorn app.main:app --reload

# In another terminal, start frontend
cd orionflow-ui
npm install
npm run dev
```

### 4. Test the API
```bash
# Health check
curl http://localhost:8000/health

# Generate a CAD model
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create a 20mm tall cylinder with 10mm radius"}'

# View API documentation
# Open http://localhost:8000/docs in browser
```

## Environment & prerequisites
- Python 3.10+ with `pip`. Create a virtualenv and install `pip install -r requirements.txt`. Key services rely on `fastapi`, `pydantic-settings`, `build123d`, `trimesh`, `groq`, and `numpy`.
- Node 20+ for the UI (`cd orionflow-ui && npm install`).
- Required env vars:
  - `GROQ_API_KEY` (LLMClient uses it to call `llama-3.3-70b-versatile` via Groq).
  - Optional Onshape sync: `ONSHAPE_DOC_ID`, `ONSHAPE_WORKSPACE_ID`, `ONSHAPE_ELEMENT_ID`.
  - `.env` is loaded automatically via `app/config.py`.

## Common commands
### Backend
- Install deps: `python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt`
- Run API with hot reload: `uvicorn app.main:app --reload`
- Run full test suite: `pytest`
- Run a single test: `pytest tests/test_context_engine.py -k reference`
- View configuration: `python -c "from app.config import settings; settings.print_config_summary()"`
- Lint/type hints are not centralized; rely on Pyright/mypy if added later.

### Frontend (inside `orionflow-ui/`)
- Install deps: `npm install`
- Start dev server: `npm run dev` (listens on 5173)
- Build bundle: `npm run build`
- Lint: `npm run lint`

## Architecture highlights

### Configuration System (NEW)
- `app/config.py` provides type-safe settings via Pydantic `BaseSettings`
- All hardcoded values moved to environment variables
- Settings loaded from `.env` file automatically
- Validation on startup (e.g., API key presence, valid values)
- Access settings anywhere: `from app.config import settings`

### FastAPI surface
- `app/main.py` exposes `/generate`, `/regenerate`, `/describe`, `/health`, and file download endpoints.
- **Full OpenAPI documentation** at `/docs` (Swagger UI) and `/redoc`
- Mounts `outputs/` for static delivery and enforces CORS from configuration.

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
- `app/context/context_engine.py` tracks session state (conversation history, active topology references, parameter history) to resolve phrases like "that edge" during multi-turn interactions.

### Domain models & compilers
- `app/domain/feature_graph_v1.py` (not shown above) represents canonical CFG v1. `feature_graph_v2.py` introduces semantic topology selectors for advanced operations; `app/compilers/build123d_compiler_v2.py` demonstrates V2 support with selector resolution and filter chains.
- `app/domain/generation_result.py` standardizes outputs across v1/v2 and carries execution traces for retries/analytics.
- `app/cad/onshape/` and `app/clients/onshape_client.py` (when configured) adapt graphs to FeatureScript and push to cloud workspaces.

### LLM integration
- `app/llm/client.py` abstracts provider-specific logic (currently Groq). It enforces JSON-only responses, performs auto-repair, and validates outputs through Pydantic schemas before the compiler sees them. The retry prompt (`app/llm/prompts.py`) includes execution traces to steer the model after failures.
- **Configuration via settings**: model name, temperature, max_tokens all configurable via `.env`.

### Dataset & validation support
- `app/services/dataset_writer.py` and `app/domain/dataset_sample.py` persist prompt/graph/trace tuples for offline learning.
- `app/validation/` and `app/services/retry_policy.py` encapsulate guardrails (sanity checks, error recovery).
- Standalone scripts like `generate_part.py`, `check_build123d.py`, and `debug_trace.py` help reproduce compiler issues.

### Frontend (orionflow-ui)
- Vite + React + TypeScript. Scripts in `package.json` handle dev/build/lint. Components are expected to call backend endpoints at `http://localhost:8000` (configure proxies if necessary). CORS is configurable via `CORS_ORIGINS` environment variable.

## Testing guidance
- Python tests use Pytest (`tests/` directory). Coverage spans compilers (`tests/test_compiler_v1.py`), constraints, retry policy, dataset ingestion, context engine, and LLM prompt handling. When debugging a failing scenario, run `pytest tests/test_feature_graph_v2.py -vv` for detailed traces.
- For quick backend smoke tests after code changes, issue a sample prompt via HTTP: `curl -X POST http://127.0.0.1:8000/generate -H "Content-Type: application/json" -d "{\"prompt\":\"Create a 20mm tall cylinder\"}"`. Geometry files will appear in `outputs/`.

## Operational tips
- `outputs/` directory is auto-created by the configuration system.
- `GenerationService` logs dataset samples even on failures—monitor the log output to avoid unbounded growth (rotate `data/` periodically).
- If Onshape credentials are absent, the service silently degrades to local Build123d. When debugging cloud sync, set `DEBUG=true` in `.env`.
- Configuration summary: Run `python -c "from app.config import settings; settings.print_config_summary()"` to view current settings.

