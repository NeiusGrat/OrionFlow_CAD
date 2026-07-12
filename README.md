# OrionFlow

AI-powered text-to-CAD for mechanical engineers. Describe a part in plain
English — get validated parametric geometry with STEP/STL/GLB exports and
editable code, in seconds.

**Live:** [orionflow.in](https://orionflow.in) (landing) ·
[app.orionflow.in](https://app.orionflow.in) (design studio)

## Architecture

```
orionflow.in ──────► Vercel  (landing/            static violet site + research pages)
app.orionflow.in ──► Vercel  (orionflow-ui/       React studio: chat, 3D viewer, OFL code panel)
      │
      ▼  VITE_API_URL
Modal (deploy/modal_app.py) ─► FastAPI (app/) ─► K2 Think ──► OFL code ─► sandbox (build123d/OCP)
      │                                          └ Groq fallback              │
      ▼                                                                       ▼
Supabase Postgres (auth, designs)                    Supabase Storage (STEP/STL/GLB artifacts)
```

A second product lives in `orion_agent/`: a FreeCAD-embedded AI copilot
(chat panel inside FreeCAD) with its own agent harness, robotics assembly
stack, and URDF export.

## Repository map

| Path | What it is |
|---|---|
| `app/` | FastAPI backend — auth, designs, billing, OFL generate/rebuild/edit API, compilers, LLM clients |
| `orionflow_ofl/` | OrionFlow Language (OFL): deterministic Python CAD DSL on build123d, plus its data pipeline |
| `orionflow-ui/` | React design studio (Vite + three.js). Ships the 20-example gallery in `public/examples/` |
| `landing/` | Static marketing site (violet/white, research articles, dark mode) served at orionflow.in |
| `orion_agent/` | FreeCAD copilot: addon (workbench, chat panel, bridge) + agent harness (spec parser, tools, repair policy, robotics/mechanical knowledge) |
| `deploy/` | Production deployment: `modal_app.py` (backend on Modal), `create_modal_secret.py` (env → Modal secret). Secrets live in the gitignored `deploy/.env.deploy` |
| `alembic/` | Database migrations (run automatically at backend boot) |
| `tests/` | Main test suite (~380 tests) — backend, OFL, agent harness |
| `scripts/` | Dataset pipeline (template gen → conversion → edits → rejections → final dataset), validators, `generate_examples.py` (showcase examples) |
| `freecad/` | FCStd ⇄ FeatureGraph extractors (incl. multimodal GNN tensors) for training data |
| `fine_tuning/` | Qwen fine-tuning scripts |
| `data/`, `CAD_DATA/` | Datasets and runtime outputs (mostly gitignored) |
| `docker/` | nginx/prometheus/grafana configs for self-hosted deployment |
| `archive/` | Retired experiments, legacy studio, obsolete pipeline versions |

## Development

```bash
# Backend (needs Docker for Postgres/Redis)
docker compose -f docker-compose.dev.yml up -d postgres redis
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000

# Studio
cd orionflow-ui && npm install && npm run dev   # http://localhost:5173

# Tests
pytest tests/                                   # main suite
pytest orionflow_ofl/tests/ orionflow_ofl/data_pipeline/tests/  # OFL suites

# Regenerate the showcase examples through the real pipeline
python scripts/generate_examples.py
```

Configuration is environment-driven (`app/config.py`, pydantic-settings).
Copy `.env.example` → `.env` for local dev. LLM providers are pluggable:
`groq`, `k2think`, `ollama` (+ `ofl_llm_fallback_provider` for automatic
failover).

## Deployment

| Piece | Host | How |
|---|---|---|
| Backend | Modal (scale-to-zero) | `python deploy/create_modal_secret.py && modal deploy deploy/modal_app.py` |
| Studio | Vercel project `orionflow` | `cd orionflow-ui && vercel deploy --prod` |
| Landing | Vercel project `orionflow-site` | `cd landing && vercel deploy --prod` |
| DB/Storage | Supabase | migrations at boot; bucket `orionflow`, SigV4 presigned URLs |

DNS (Hostinger): `A @ → 76.76.21.21`, `CNAME www → cname.vercel-dns.com`
(308-redirects to apex), `CNAME app → cname.vercel-dns.com`.

## FreeCAD copilot

Install `orion_agent/addon/` as a FreeCAD workbench (FreeCAD ≥ 1.0). The
chat panel talks to the local harness, which drives FreeCAD through the
bridge — spec parsing, standards lookup, parametric modeling, robotics
assemblies, URDF export. See `orion_agent/tests/` for behavior coverage.
