"""
OrionFlow Studio - Live build123d Test Bench (Web)

A single-file FastAPI app that lets you paste a natural-language prompt
and build123d code, run it, and see the resulting 3D model in your browser
with a SolidWorks-style CAD viewer: bright viewport, satin-finish material,
visible feature edges + holes, bounding-box dimension annotations, and
a prominent X/Y/Z origin frame.

Run:
    python studio.py

Then open: http://127.0.0.1:7860
"""
from __future__ import annotations

import io
import sys
import time
import uuid
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn


ROOT = Path(__file__).parent.resolve()
STUDIO_DIR = ROOT / "outputs" / "studio"
STUDIO_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="OrionFlow Studio")
app.mount("/models", StaticFiles(directory=str(STUDIO_DIR)), name="models")


# ---------------------------------------------------------------------------
# Code execution
# ---------------------------------------------------------------------------

STRIP_PREFIXES = (
    "export_step(",
    "export_stl(",
    "export_gltf(",
    "show(",
    "show_object(",
)


def _strip_io_lines(code: str) -> str:
    keep = []
    for line in code.splitlines():
        s = line.strip()
        if any(s.startswith(p) for p in STRIP_PREFIXES):
            continue
        keep.append(line)
    return "\n".join(keep)


def _find_result(ns: dict) -> Any:
    for name in ("result", "part", "solid", "model", "shape"):
        if name in ns:
            obj = ns[name]
            return obj.part if hasattr(obj, "part") and not hasattr(obj, "wrapped") else obj
    return None


def _validate(shape) -> dict:
    report: dict = {}
    try:
        report["volume_mm3"] = round(float(shape.volume), 4)
    except Exception as e:
        report["volume_error"] = str(e)
    try:
        bb = shape.bounding_box()
        report["bbox"] = {
            "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
            "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
            "size": [
                round(bb.max.X - bb.min.X, 3),
                round(bb.max.Y - bb.min.Y, 3),
                round(bb.max.Z - bb.min.Z, 3),
            ],
            "center": [
                round((bb.min.X + bb.max.X) / 2, 3),
                round((bb.min.Y + bb.max.Y) / 2, 3),
                round((bb.min.Z + bb.max.Z) / 2, 3),
            ],
        }
    except Exception as e:
        report["bbox_error"] = str(e)
    try:
        report["topology"] = {
            "faces": len(shape.faces()),
            "edges": len(shape.edges()),
            "vertices": len(shape.vertices()),
        }
    except Exception as e:
        report["topology_error"] = str(e)
    try:
        from OCP.BRepCheck import BRepCheck_Analyzer
        report["watertight"] = bool(BRepCheck_Analyzer(shape.wrapped).IsValid())
    except Exception as e:
        report["watertight_error"] = str(e)
    return report


class RunRequest(BaseModel):
    prompt: str = ""
    code: str


@app.post("/run")
def run(req: RunRequest):
    code = _strip_io_lines(req.code)
    ns: dict = {}
    stdout_buf = io.StringIO()
    real_stdout = sys.stdout
    t0 = time.time()
    try:
        exec("from build123d import *", ns)
        sys.stdout = stdout_buf
        exec(code, ns)
    except Exception as e:
        sys.stdout = real_stdout
        return JSONResponse(
            {
                "ok": False,
                "error_type": type(e).__name__,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "stdout": stdout_buf.getvalue(),
                "elapsed_ms": int((time.time() - t0) * 1000),
            },
            status_code=200,
        )
    finally:
        sys.stdout = real_stdout

    shape = _find_result(ns)
    if shape is None:
        available = [k for k in ns if not k.startswith("_") and k not in ("build123d",)]
        return {
            "ok": False,
            "error_type": "NoResultVar",
            "error": "No `result`, `part`, `solid`, `model`, or `shape` variable found.",
            "available_vars": available,
            "stdout": stdout_buf.getvalue(),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    model_id = uuid.uuid4().hex[:12]
    glb_path = STUDIO_DIR / f"{model_id}.glb"
    step_path = STUDIO_DIR / f"{model_id}.step"
    stl_path = STUDIO_DIR / f"{model_id}.stl"

    try:
        from build123d import export_gltf, export_step, export_stl
        export_gltf(shape, str(glb_path), binary=True)
        export_step(shape, str(step_path))
        export_stl(shape, str(stl_path))
    except Exception as e:
        return {
            "ok": False,
            "error_type": "ExportError",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "stdout": stdout_buf.getvalue(),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    return {
        "ok": True,
        "model_id": model_id,
        "glb_url": f"/models/{model_id}.glb",
        "step_url": f"/models/{model_id}.step",
        "stl_url": f"/models/{model_id}.stl",
        "validation": _validate(shape),
        "stdout": stdout_buf.getvalue(),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Frontend — SolidWorks-style viewer in Three.js
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>OrionFlow Studio</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
  :root {
    --bg: #0c0e13;
    --panel: #13161d;
    --panel-2: #1a1e27;
    --panel-3: #20242e;
    --border: #262b36;
    --border-hi: #343a48;
    --text: #e6eaf2;
    --text-dim: #b6bdcc;
    --muted: #7d8699;
    --accent: #4d9eff;
    --accent-2: #6cb0ff;
    --accent-soft: rgba(77, 158, 255, 0.14);
    --ok: #4ade80;
    --err: #f87171;
    --warn: #fbbf24;
    --mono: ui-monospace, "JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
    --ui: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; background: var(--bg); color: var(--text);
    font-family: var(--ui); font-size: 13px; overflow: hidden; -webkit-font-smoothing: antialiased; }
  kbd { font-family: var(--mono); background: var(--panel-3); border: 1px solid var(--border);
    border-radius: 3px; padding: 1px 5px; font-size: 10.5px; color: var(--text-dim); }

  /* HEADER */
  header { display: flex; align-items: center; height: 46px; padding: 0 14px;
    background: linear-gradient(180deg, #161a22 0%, #11141b 100%);
    border-bottom: 1px solid var(--border); gap: 14px; z-index: 10; position: relative; }
  .brand { display: flex; align-items: center; gap: 10px; padding-right: 14px;
    border-right: 1px solid var(--border); height: 100%; }
  .brand-mark { width: 24px; height: 24px; border-radius: 6px; position: relative;
    background: conic-gradient(from 210deg at 50% 50%, #4d9eff, #6cb0ff, #a884ff, #ff7e9c, #4d9eff);
    box-shadow: 0 0 18px rgba(77, 158, 255, 0.5), inset 0 0 6px rgba(0,0,0,0.3); }
  .brand-mark::after { content: ''; position: absolute; inset: 5px; border-radius: 4px;
    background: var(--panel); }
  .brand-mark::before { content: ''; position: absolute; inset: 8px; border-radius: 3px;
    background: linear-gradient(135deg, #4d9eff, #a884ff); z-index: 1; }
  .brand-title { font-weight: 600; font-size: 14px; letter-spacing: 0.2px; }
  .brand-sub { color: var(--muted); font-size: 10.5px; margin-left: 6px;
    padding: 2px 7px; border: 1px solid var(--border); border-radius: 3px;
    text-transform: uppercase; letter-spacing: 0.7px; font-weight: 500; }
  .spacer { flex: 1; }
  .actions { display: flex; gap: 8px; align-items: center; }
  button { font-family: inherit; }
  button.ghost { background: transparent; border: 1px solid var(--border);
    color: var(--text-dim); padding: 7px 13px; border-radius: 5px; cursor: pointer;
    font-size: 12px; transition: all 0.12s; }
  button.ghost:hover { background: var(--panel-2); color: var(--text); border-color: var(--border-hi); }
  button.primary {
    background: linear-gradient(180deg, #5aa6ff 0%, #4d9eff 100%);
    color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer;
    font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 8px;
    box-shadow: 0 1px 0 rgba(255,255,255,0.15) inset, 0 1px 8px rgba(77,158,255,0.35);
  }
  button.primary:hover { background: linear-gradient(180deg, #6cb0ff 0%, #5aa6ff 100%); }
  button.primary:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
  button.primary svg { width: 11px; height: 11px; }

  /* MAIN LAYOUT */
  main { display: grid; grid-template-columns: 460px 1fr;
    height: calc(100vh - 46px - 30px); }

  /* Editor pane */
  .editor-pane { background: var(--panel); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; min-width: 0; }
  .pane-head { padding: 0 14px; border-bottom: 1px solid var(--border);
    color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.8px;
    font-weight: 600; display: flex; justify-content: space-between; align-items: center; height: 34px; }
  .pane-head .examples { display: flex; gap: 2px; text-transform: none; font-weight: 500; letter-spacing: 0; }
  .pane-head .examples a { color: var(--muted); font-size: 11.5px; cursor: pointer;
    padding: 3px 9px; border-radius: 3px; }
  .pane-head .examples a:hover { color: var(--accent); background: var(--accent-soft); }
  .prompt-row { padding: 9px 12px; border-bottom: 1px solid var(--border);
    display: flex; gap: 9px; align-items: center; background: var(--panel-2); }
  .prompt-row .lbl { color: var(--muted); font-size: 10.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.7px; }
  .prompt-row input { flex: 1; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 7px 11px; border-radius: 4px; font-size: 12.5px; outline: none;
    transition: border-color 0.12s; font-family: var(--ui); }
  .prompt-row input::placeholder { color: var(--muted); }
  .prompt-row input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
  #editor { flex: 1; background: var(--bg); color: var(--text); font-family: var(--mono);
    font-size: 12.5px; padding: 14px; border: none; outline: none; resize: none;
    line-height: 1.6; tab-size: 4; white-space: pre; overflow: auto; }
  #editor::selection { background: rgba(77,158,255,0.3); }

  /* === SolidWorks-style light viewport === */
  .viewport-pane { position: relative; overflow: hidden;
    background: linear-gradient(180deg, #b6cce2 0%, #d6e0eb 45%, #eef2f7 100%); }
  #canvas { width: 100%; height: 100%; display: block; }

  .vp-overlay { position: absolute; pointer-events: none; z-index: 5; }
  .vp-tl { top: 12px; left: 12px; }
  .vp-tr { top: 12px; right: 12px; }
  .vp-bl { bottom: 12px; left: 12px; }
  .vp-br { bottom: 12px; right: 12px; }

  /* Floating panels — frosted dark on light bg */
  .vp-group { background: rgba(18, 22, 30, 0.82); backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 3px;
    display: inline-flex; gap: 1px; pointer-events: auto;
    box-shadow: 0 6px 22px rgba(20,30,50,0.25), 0 1px 0 rgba(255,255,255,0.05) inset; }
  .vp-group.col { flex-direction: column; }
  .vp-group button {
    background: transparent; border: none; color: #d0d5e0; cursor: pointer;
    padding: 6px 11px; border-radius: 4px; font-size: 11px; font-weight: 500;
    min-width: 38px; transition: all 0.1s; letter-spacing: 0.3px;
  }
  .vp-group button:hover { background: rgba(255,255,255,0.08); color: white; }
  .vp-group button.active { background: var(--accent-soft); color: var(--accent-2); }
  .vp-group.col button { min-width: auto; padding: 7px 9px; font-size: 13px; }

  .stats-card { background: rgba(18, 22, 30, 0.85); backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; padding: 11px 14px;
    pointer-events: auto; font-family: var(--mono); font-size: 11px; line-height: 1.85;
    min-width: 220px; box-shadow: 0 6px 22px rgba(20,30,50,0.25); display: none; color: #d0d5e0; }
  .stats-card.visible { display: block; }
  .stats-card .ttl { font-family: var(--ui); font-size: 10px; color: #8b94a8;
    text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin-bottom: 6px;
    padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.08); }
  .stats-card .row { display: flex; justify-content: space-between; gap: 16px; }
  .stats-card .lbl { color: #8b94a8; }
  .stats-card .val { color: #e6eaf2; }
  .stats-card .val.ok { color: var(--ok); }
  .stats-card .val.err { color: var(--err); }

  #gizmo { width: 96px; height: 96px; display: block; }

  /* Empty-state visible on LIGHT viewport */
  .empty-state { position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; color: #4a5567; pointer-events: none;
    text-align: center; gap: 12px; z-index: 3; }
  .empty-state svg { opacity: 0.35; stroke: #4a5567; }
  .empty-state .title { font-size: 14px; color: #2a3340; font-weight: 600; }
  .empty-state .hint { font-size: 12px; color: #4a5567; }
  .empty-state kbd { background: rgba(0,0,0,0.05); color: #2a3340; border-color: rgba(0,0,0,0.12); }

  .loading-bar { position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent) 50%, transparent);
    background-size: 200% 100%; animation: shimmer 1.1s linear infinite;
    display: none; z-index: 9; }
  .loading-bar.visible { display: block; }
  @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

  /* STATUS BAR */
  .statusbar { height: 30px; background: var(--panel);
    border-top: 1px solid var(--border); padding: 0 14px;
    display: flex; align-items: center; gap: 14px; font-size: 11px; color: var(--text-dim);
    font-family: var(--mono); }
  .statusbar .pill { padding: 2px 9px; border-radius: 10px; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.7px; font-weight: 600; font-family: var(--ui); }
  .pill.idle    { background: var(--panel-3); color: var(--muted); }
  .pill.running { background: rgba(251,191,36,0.15); color: var(--warn); }
  .pill.ok      { background: rgba(74,222,128,0.15); color: var(--ok); }
  .pill.err     { background: rgba(248,113,113,0.18); color: var(--err); }
  .statusbar .sep { width: 1px; height: 14px; background: var(--border); }
  .statusbar .err-detail { color: var(--err); overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; max-width: 50vw; }
  .statusbar .downloads { display: none; gap: 6px; margin-left: auto; }
  .statusbar .downloads.visible { display: flex; }
  .statusbar .downloads a { color: var(--accent); text-decoration: none; padding: 2px 9px;
    border: 1px solid var(--border); border-radius: 3px; font-size: 10.5px; font-weight: 500; }
  .statusbar .downloads a:hover { background: var(--accent-soft); border-color: var(--accent); }

  /* ERROR CONSOLE DRAWER */
  .console { position: fixed; bottom: 30px; left: 460px; right: 0;
    background: var(--panel); border-top: 2px solid var(--err);
    padding: 12px 16px; max-height: 260px; overflow: auto;
    font-family: var(--mono); font-size: 11.5px; color: var(--text); display: none;
    box-shadow: 0 -6px 22px rgba(0,0,0,0.4); z-index: 15; }
  .console.visible { display: block; }
  .console .close { float: right; cursor: pointer; color: var(--muted); font-size: 12px;
    padding: 2px 8px; border: 1px solid var(--border); border-radius: 3px; }
  .console .close:hover { color: var(--text); border-color: var(--border-hi); }
  .console .head { color: var(--err); font-weight: 600; margin-bottom: 6px; font-family: var(--ui);
    font-size: 12px; }
  .console pre { margin: 6px 0 0 0; white-space: pre-wrap; word-break: break-word;
    color: var(--text-dim); }
</style>
</head>
<body>

<header>
  <div class="brand">
    <div class="brand-mark"></div>
    <div>
      <span class="brand-title">OrionFlow Studio</span>
      <span class="brand-sub">build123d</span>
    </div>
  </div>
  <div class="spacer"></div>
  <div class="actions">
    <button class="ghost" id="reset-btn">Clear</button>
    <button class="primary" id="run-btn">
      <svg viewBox="0 0 12 12" fill="currentColor"><path d="M3 1.5l7 4.5-7 4.5V1.5z"/></svg>
      Run <kbd style="background:rgba(255,255,255,0.18);border-color:rgba(255,255,255,0.25);color:white">Ctrl+Enter</kbd>
    </button>
  </div>
</header>

<main>
  <div class="editor-pane">
    <div class="pane-head">
      <span>Source &mdash; build123d</span>
      <div class="examples">
        <a data-example="washer">washer</a>
        <a data-example="bracket">bracket</a>
        <a data-example="flange">flange</a>
        <a data-example="gear">gear</a>
      </div>
    </div>
    <div class="prompt-row">
      <span class="lbl">Prompt</span>
      <input id="prompt" type="text" placeholder="Describe the part (notes-only for now — will drive the fine-tuned model)" />
    </div>
    <textarea id="editor" spellcheck="false"></textarea>
  </div>

  <div class="viewport-pane">
    <canvas id="canvas"></canvas>
    <div class="loading-bar" id="loading-bar"></div>

    <div class="empty-state" id="empty-state">
      <svg width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
        <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
        <line x1="12" y1="22.08" x2="12" y2="12"></line>
      </svg>
      <div class="title">No model loaded</div>
      <div class="hint">Press <b>Run</b> or <kbd>Ctrl+Enter</kbd> to compile</div>
    </div>

    <div class="vp-overlay vp-tl">
      <div class="vp-group" id="view-presets">
        <button data-view="iso" class="active">ISO</button>
        <button data-view="top">Top</button>
        <button data-view="front">Front</button>
        <button data-view="right">Right</button>
      </div>
    </div>

    <div class="vp-overlay vp-tr">
      <div class="vp-group" id="render-modes">
        <button data-mode="shaded-edges" class="active">Shaded + Edges</button>
        <button data-mode="shaded">Shaded</button>
        <button data-mode="wireframe">Wireframe</button>
      </div>
    </div>

    <div class="vp-overlay vp-bl">
      <div class="stats-card" id="stats">
        <div class="ttl">Geometry</div>
        <div class="row"><span class="lbl">Volume</span><span class="val" id="s-vol">&mdash;</span></div>
        <div class="row"><span class="lbl">Bbox</span><span class="val" id="s-bbox">&mdash;</span></div>
        <div class="row"><span class="lbl">Center</span><span class="val" id="s-center">&mdash;</span></div>
        <div class="row"><span class="lbl">Topology</span><span class="val" id="s-topo">&mdash;</span></div>
        <div class="row"><span class="lbl">Watertight</span><span class="val" id="s-wt">&mdash;</span></div>
      </div>
    </div>

    <div class="vp-overlay vp-br">
      <canvas id="gizmo"></canvas>
    </div>

    <div class="vp-overlay" style="bottom: 124px; right: 12px;">
      <div class="vp-group col">
        <button id="fit-btn"   title="Fit view">&#9974;</button>
        <button id="dim-btn"   class="active" title="Toggle dimensions">D</button>
        <button id="grid-btn"  class="active" title="Toggle grid">&#9638;</button>
        <button id="axes-btn"  class="active" title="Toggle origin XYZ">&#10010;</button>
        <button id="ortho-btn" title="Toggle ortho / perspective">&#9633;</button>
      </div>
    </div>
  </div>
</main>

<div class="statusbar">
  <span class="pill idle" id="status-pill">idle</span>
  <span id="status-text">Ready</span>
  <span class="sep"></span>
  <span id="elapsed"></span>
  <span class="err-detail" id="err-detail"></span>
  <div class="downloads" id="downloads">
    <a id="dl-step" target="_blank" download>STEP</a>
    <a id="dl-stl" target="_blank" download>STL</a>
    <a id="dl-glb" target="_blank" download>GLB</a>
  </div>
</div>

<div class="console" id="console">
  <span class="close" id="console-close">close &#x2715;</span>
  <div class="head" id="console-head"></div>
  <pre id="console-body"></pre>
</div>

<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.161.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.161.0/examples/jsm/"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// ============ Examples ============
const EXAMPLES = {
  washer: `from build123d import *

# M4 Washer (DIN 125A)
with BuildPart() as part:
    with BuildSketch():
        Circle(radius=4.5)
        Circle(radius=2.15, mode=Mode.SUBTRACT)
    extrude(amount=0.8)

result = part.part
`,
  bracket: `from build123d import *

base_l, base_w, base_t = 110, 80, 10
boss_d, bore_d, boss_w = 40, 20, 40
arm_t, height = 12, 70
hole_d, hx, hy = 10, 80, 60

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        RectangleRounded(base_l, base_w, radius=6)
    extrude(amount=base_t)

    arm_h = height - base_t
    for sx in (-1, 1):
        with Locations((sx * (boss_w/2 - arm_t/2), 0, base_t)):
            Box(arm_t, boss_w, arm_h, align=(Align.CENTER, Align.CENTER, Align.MIN))

    with Locations((0, 0, height)):
        Cylinder(radius=boss_d/2, height=boss_w, rotation=(90, 0, 0))
    with Locations((0, 0, height)):
        Cylinder(radius=bore_d/2, height=boss_w + 2, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

    for x in (-hx/2, hx/2):
        for y in (-hy/2, hy/2):
            with Locations((x, y, 0)):
                Cylinder(radius=hole_d/2, height=base_t + 2, mode=Mode.SUBTRACT)

result = part.part
`,
  flange: `from build123d import *

body_d, bore_d, body_h = 10.0, 5.0, 32.0
flange_d, flange_h = 18.0, 4.0

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        Circle(flange_d / 2)
    extrude(amount=flange_h)

    with BuildSketch(Plane.XY.offset(flange_h)):
        Circle(body_d / 2)
    extrude(amount=body_h)

    with BuildSketch(Plane.XY):
        Circle(bore_d / 2)
    extrude(amount=flange_h + body_h, mode=Mode.SUBTRACT)

    chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.3)

result = part.part
`,
  gear: `from build123d import *
import math

# Simple spur gear (polar polygon teeth)
n_teeth = 18
module = 2.0
thickness = 6.0
bore_d = 8.0

pitch_r = module * n_teeth / 2
addendum = module
dedendum = 1.25 * module
outer_r = pitch_r + addendum
root_r = pitch_r - dedendum

pts = []
for i in range(n_teeth * 4):
    if i % 4 == 0:   r = root_r
    elif i % 4 == 1: r = pitch_r
    elif i % 4 == 2: r = outer_r
    else:            r = pitch_r
    a = 2 * math.pi * i / (n_teeth * 4)
    pts.append((r * math.cos(a), r * math.sin(a)))

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        with BuildLine() as bl:
            Polyline(*pts, close=True)
        make_face()
        Circle(bore_d / 2, mode=Mode.SUBTRACT)
    extrude(amount=thickness)

result = part.part
`,
};

// ============ DOM refs ============
const editor = document.getElementById('editor');
const promptInput = document.getElementById('prompt');
const runBtn = document.getElementById('run-btn');
const resetBtn = document.getElementById('reset-btn');
const canvas = document.getElementById('canvas');
const gizmoCanvas = document.getElementById('gizmo');
const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const elapsedEl = document.getElementById('elapsed');
const errDetail = document.getElementById('err-detail');
const downloads = document.getElementById('downloads');
const dlGlb = document.getElementById('dl-glb');
const dlStep = document.getElementById('dl-step');
const dlStl = document.getElementById('dl-stl');
const emptyState = document.getElementById('empty-state');
const loadingBar = document.getElementById('loading-bar');
const statsCard = document.getElementById('stats');
const consoleEl = document.getElementById('console');
const consoleHead = document.getElementById('console-head');
const consoleBody = document.getElementById('console-body');

editor.value = EXAMPLES.bracket;

document.querySelectorAll('[data-example]').forEach(b => {
  b.addEventListener('click', () => { editor.value = EXAMPLES[b.dataset.example]; });
});
resetBtn.addEventListener('click', () => { editor.value = ''; promptInput.value = ''; });
document.getElementById('console-close').addEventListener('click',
  () => consoleEl.classList.remove('visible'));

editor.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = editor.selectionStart, t = editor.selectionEnd;
    editor.value = editor.value.slice(0, s) + '    ' + editor.value.slice(t);
    editor.selectionStart = editor.selectionEnd = s + 4;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    runBtn.click();
  }
});

// ============ Three.js scene (Z-up CAD convention) ============
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

let camera = makePerspective();
function makePerspective() {
  const c = new THREE.PerspectiveCamera(40, 1, 0.1, 100000);
  c.position.set(140, -140, 110);
  c.up.set(0, 0, 1);
  return c;
}

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.09;
controls.rotateSpeed = 0.75;
controls.zoomSpeed = 0.9;
controls.target.set(0, 0, 0);

// Studio lighting (soft + crisp specular)
const key = new THREE.DirectionalLight(0xffffff, 0.6);
key.position.set(200, -250, 350); scene.add(key);
const fill = new THREE.DirectionalLight(0xcfe0ff, 0.22);
fill.position.set(-220, 100, 80); scene.add(fill);
const rim = new THREE.DirectionalLight(0xffe1bf, 0.18);
rim.position.set(0, 250, -120); scene.add(rim);

// ============ Floor grid (Z-up) ============
let grid = null;
const gridParent = new THREE.Group();
scene.add(gridParent);

function rebuildGrid(maxDim) {
  if (grid) {
    gridParent.remove(grid);
    grid.geometry.dispose(); grid.material.dispose();
  }
  const base = Math.max(50, Math.pow(10, Math.ceil(Math.log10(Math.max(maxDim, 10)))));
  const size = base * 4;
  grid = new THREE.GridHelper(size, 40, 0x6f7d92, 0xb3becf);
  grid.rotation.x = Math.PI / 2;
  grid.material.transparent = true;
  grid.material.opacity = 0.45;
  grid.material.depthWrite = false;
  gridParent.add(grid);
}
rebuildGrid(100);

// ============ Origin XYZ frame (SolidWorks-style triad at world origin) ============
const originFrame = new THREE.Group();
scene.add(originFrame);

function makeOriginAxis(dir, color, hex, label, length) {
  const g = new THREE.Group();
  // Shaft
  const shaftLen = length * 0.86;
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(length * 0.012, length * 0.012, shaftLen, 12),
    new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 })
  );
  shaft.position.copy(dir.clone().multiplyScalar(shaftLen / 2));
  shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  shaft.renderOrder = 999;
  g.add(shaft);
  // Arrowhead
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(length * 0.04, length * 0.14, 16),
    new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 })
  );
  cone.position.copy(dir.clone().multiplyScalar(shaftLen + length * 0.07));
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  cone.renderOrder = 999;
  g.add(cone);
  // Label sprite
  const sp = textSprite(label, hex, 64, true);
  sp.position.copy(dir.clone().multiplyScalar(length * 1.08));
  sp.renderOrder = 1000;
  // Scale sprite to ~10% of axis length in world units (sprite is 1 unit by default)
  const ss = length * 0.18;
  sp.scale.set(ss, ss, ss);
  g.add(sp);
  return g;
}

function textSprite(text, hex, fontPx = 56, bold = true) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const ctx = c.getContext('2d');
  ctx.font = (bold ? 'bold ' : '') + fontPx + 'px -apple-system, "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = hex;
  // subtle outline for readability on any background
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 5;
  ctx.strokeText(text, 64, 70);
  ctx.fillText(text, 64, 70);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const s = new THREE.Sprite(m);
  return s;
}

function rebuildOriginFrame(maxDim) {
  while (originFrame.children.length) {
    const c = originFrame.children[0];
    originFrame.remove(c);
    c.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
  }
  const len = Math.max(maxDim * 0.45, 18);
  originFrame.add(makeOriginAxis(new THREE.Vector3(1, 0, 0), 0xe53935, '#c62828', 'X', len));
  originFrame.add(makeOriginAxis(new THREE.Vector3(0, 1, 0), 0x2e7d32, '#1b5e20', 'Y', len));
  originFrame.add(makeOriginAxis(new THREE.Vector3(0, 0, 1), 0x1565c0, '#0d47a1', 'Z', len));
  // Tiny origin sphere
  const sph = new THREE.Mesh(
    new THREE.SphereGeometry(len * 0.025, 16, 16),
    new THREE.MeshBasicMaterial({ color: 0x2a3340, depthTest: false })
  );
  sph.renderOrder = 999;
  originFrame.add(sph);
}
rebuildOriginFrame(60);

// ============ Model + edges ============
const modelGroup = new THREE.Group();
scene.add(modelGroup);
const dimGroup = new THREE.Group();
scene.add(dimGroup);

let currentMesh = null;
let currentEdges = null;
let renderMode = 'shaded-edges';
let dimsVisible = true;

function clearModel() {
  while (modelGroup.children.length) {
    const c = modelGroup.children[0];
    modelGroup.remove(c);
    c.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        if (Array.isArray(o.material)) o.material.forEach(m => m.dispose());
        else o.material.dispose();
      }
    });
  }
  currentMesh = null; currentEdges = null;
}

function clearDims() {
  while (dimGroup.children.length) {
    const c = dimGroup.children[0];
    dimGroup.remove(c);
    c.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
  }
}

function loadSTL(url) {
  return new Promise((resolve, reject) => {
    new STLLoader().load(url, resolve, undefined, reject);
  });
}

// ============ Dimension annotations (SW-style bbox dimensions) ============
const DIM_COLOR = 0x14365e;       // dark navy
const DIM_LABEL_BG = '#ffffff';
const DIM_LABEL_FG = '#14365e';

function dimLabelSprite(text, sz) {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 80;
  const ctx = c.getContext('2d');
  // background plate
  ctx.fillStyle = DIM_LABEL_BG;
  ctx.strokeStyle = '#14365e';
  ctx.lineWidth = 3;
  const r = 10;
  ctx.beginPath();
  ctx.moveTo(r, 2);
  ctx.lineTo(c.width - r, 2);
  ctx.quadraticCurveTo(c.width - 2, 2, c.width - 2, r);
  ctx.lineTo(c.width - 2, c.height - r);
  ctx.quadraticCurveTo(c.width - 2, c.height - 2, c.width - r, c.height - 2);
  ctx.lineTo(r, c.height - 2);
  ctx.quadraticCurveTo(2, c.height - 2, 2, c.height - r);
  ctx.lineTo(2, r);
  ctx.quadraticCurveTo(2, 2, r, 2);
  ctx.closePath();
  ctx.fill(); ctx.stroke();
  ctx.font = 'bold 38px "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = DIM_LABEL_FG;
  ctx.fillText(text, c.width / 2, c.height / 2 + 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sp = new THREE.Sprite(mat);
  const w = sz * 1.4, h = w * 0.32;
  sp.scale.set(w, h, 1);
  sp.renderOrder = 1100;
  return sp;
}

function lineSeg(pts, color = DIM_COLOR, opacity = 0.9) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false });
  const l = new THREE.LineSegments(g, m);
  l.renderOrder = 1050;
  return l;
}

function lineStrip(pts, color = DIM_COLOR, opacity = 0.9) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false });
  const l = new THREE.Line(g, m);
  l.renderOrder = 1050;
  return l;
}

function arrowHead(at, dir, sz) {
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(sz * 0.35, sz, 12),
    new THREE.MeshBasicMaterial({ color: DIM_COLOR, depthTest: false })
  );
  cone.position.copy(at);
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  cone.renderOrder = 1060;
  return cone;
}

function makeDim(p1, p2, offDir, label, maxDim) {
  const out = new THREE.Group();
  const off = maxDim * 0.18 + 4;
  const ext = offDir.clone().normalize().multiplyScalar(off);
  const dp1 = p1.clone().add(ext);
  const dp2 = p2.clone().add(ext);

  // Extension lines (with a tiny gap from the part)
  const gap = maxDim * 0.012;
  const gapDir = offDir.clone().normalize().multiplyScalar(gap);
  out.add(lineSeg([p1.clone().add(gapDir), dp1, p2.clone().add(gapDir), dp2]));

  // Dimension line (continuous between dp1 and dp2)
  out.add(lineStrip([dp1, dp2]));

  // Arrows pointing inward along the dim line
  const along = new THREE.Vector3().subVectors(dp2, dp1).normalize();
  const arrowSz = maxDim * 0.028 + 0.4;
  out.add(arrowHead(dp1, along, arrowSz));
  out.add(arrowHead(dp2, along.clone().negate(), arrowSz));

  // Label at midpoint, lifted slightly along offset direction
  const mid = new THREE.Vector3().addVectors(dp1, dp2).multiplyScalar(0.5);
  const sp = dimLabelSprite(label, maxDim);
  sp.position.copy(mid).add(offDir.clone().normalize().multiplyScalar(maxDim * 0.05));
  out.add(sp);
  return out;
}

function buildDimensions(bbox) {
  clearDims();
  if (!dimsVisible) return;
  const sz = new THREE.Vector3(); bbox.getSize(sz);
  const maxDim = Math.max(sz.x, sz.y, sz.z, 1);
  const x0 = bbox.min.x, y0 = bbox.min.y, z0 = bbox.min.z;
  const x1 = bbox.max.x, y1 = bbox.max.y, z1 = bbox.max.z;

  // X dimension: bottom-front edge, dim line offset in -Y
  dimGroup.add(makeDim(
    new THREE.Vector3(x0, y0, z0),
    new THREE.Vector3(x1, y0, z0),
    new THREE.Vector3(0, -1, 0),
    `${sz.x.toFixed(2)} mm`,
    maxDim,
  ));
  // Y dimension: bottom-right edge, dim line offset in +X
  dimGroup.add(makeDim(
    new THREE.Vector3(x1, y0, z0),
    new THREE.Vector3(x1, y1, z0),
    new THREE.Vector3(1, 0, 0),
    `${sz.y.toFixed(2)} mm`,
    maxDim,
  ));
  // Z dimension: front-left vertical edge, dim line offset in -X
  dimGroup.add(makeDim(
    new THREE.Vector3(x0, y0, z0),
    new THREE.Vector3(x0, y0, z1),
    new THREE.Vector3(-1, 0, 0),
    `${sz.z.toFixed(2)} mm`,
    maxDim,
  ));
}

// ============ Show / render mode ============
async function showModel(url) {
  clearModel();
  loadingBar.classList.add('visible');
  try {
    const geom = await loadSTL(url);
    geom.computeVertexNormals();
    geom.computeBoundingBox();

    // Satin "default CAD plastic" material — SolidWorks-like
    const mat = new THREE.MeshStandardMaterial({
      color: 0xd9dee5,
      metalness: 0.18,
      roughness: 0.5,
      envMapIntensity: 0.95,
      flatShading: false,
    });
    currentMesh = new THREE.Mesh(geom, mat);
    modelGroup.add(currentMesh);

    // Crisp feature edges (holes, fillets, sharp corners show clearly)
    const edgeGeom = new THREE.EdgesGeometry(geom, 28);
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0x0e1d33, transparent: true, opacity: 0.9,
    });
    edgeMat.polygonOffset = true; edgeMat.polygonOffsetFactor = -1;
    currentEdges = new THREE.LineSegments(edgeGeom, edgeMat);
    currentMesh.add(currentEdges);

    applyRenderMode();

    const bb = geom.boundingBox.clone();
    const sz = new THREE.Vector3(); bb.getSize(sz);
    const maxDim = Math.max(sz.x, sz.y, sz.z, 1);
    rebuildGrid(maxDim);
    rebuildOriginFrame(maxDim);
    buildDimensions(bb);

    emptyState.style.display = 'none';
    fitView();
  } catch (e) {
    console.error('STL load failed', e);
  } finally {
    loadingBar.classList.remove('visible');
  }
}

function applyRenderMode() {
  if (!currentMesh) return;
  if (renderMode === 'shaded-edges') {
    currentMesh.visible = true; currentMesh.material.wireframe = false;
    if (currentEdges) currentEdges.visible = true;
  } else if (renderMode === 'shaded') {
    currentMesh.visible = true; currentMesh.material.wireframe = false;
    if (currentEdges) currentEdges.visible = false;
  } else if (renderMode === 'wireframe') {
    currentMesh.visible = true; currentMesh.material.wireframe = true;
    if (currentEdges) currentEdges.visible = false;
  }
}

document.querySelectorAll('#render-modes button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#render-modes button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    renderMode = b.dataset.mode;
    applyRenderMode();
  });
});

// ============ View presets ============
let currentViewName = 'iso';

function setView(name) {
  let center = new THREE.Vector3(), maxDim = 100;
  if (currentMesh) {
    const bb = new THREE.Box3().setFromObject(currentMesh);
    bb.getCenter(center);
    const sz = new THREE.Vector3(); bb.getSize(sz);
    maxDim = Math.max(sz.x, sz.y, sz.z, 1);
  }
  // Extra zoom-out so dimension annotations are visible
  const dist = maxDim * 2.9 + 8;
  controls.target.copy(center);
  const eps = dist * 0.0008;
  if (name === 'top')   camera.position.set(center.x + eps, center.y - eps * 2, center.z + dist);
  if (name === 'front') camera.position.set(center.x, center.y - dist, center.z + eps);
  if (name === 'right') camera.position.set(center.x + dist, center.y + eps, center.z + eps);
  if (name === 'iso')   camera.position.set(center.x + dist * 0.72, center.y - dist * 0.72, center.z + dist * 0.55);
  camera.up.set(0, 0, 1);
  controls.update();
}
function fitView() { setView(currentViewName); }

document.querySelectorAll('#view-presets button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#view-presets button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    currentViewName = b.dataset.view;
    setView(currentViewName);
  });
});

document.getElementById('fit-btn').addEventListener('click', fitView);
document.getElementById('dim-btn').addEventListener('click', (e) => {
  dimsVisible = !dimsVisible;
  e.currentTarget.classList.toggle('active', dimsVisible);
  if (currentMesh) {
    const bb = new THREE.Box3().setFromObject(currentMesh);
    buildDimensions(bb);
  } else {
    clearDims();
  }
});
document.getElementById('grid-btn').addEventListener('click', (e) => {
  gridParent.visible = !gridParent.visible;
  e.currentTarget.classList.toggle('active', gridParent.visible);
});
document.getElementById('axes-btn').addEventListener('click', (e) => {
  originFrame.visible = !originFrame.visible;
  e.currentTarget.classList.toggle('active', originFrame.visible);
});

let ortho = false;
document.getElementById('ortho-btn').addEventListener('click', (e) => {
  ortho = !ortho;
  e.currentTarget.classList.toggle('active', ortho);
  swapCamera();
});

function swapCamera() {
  const oldPos = camera.position.clone();
  const oldTarget = controls.target.clone();
  const d = oldPos.distanceTo(oldTarget);
  if (ortho) {
    const aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
    const half = d * 0.55;
    camera = new THREE.OrthographicCamera(-half * aspect, half * aspect, half, -half, 0.1, 100000);
  } else {
    camera = makePerspective();
  }
  camera.position.copy(oldPos);
  camera.up.set(0, 0, 1);
  controls.object = camera;
  controls.target.copy(oldTarget);
  controls.update();
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  if (camera.isPerspectiveCamera) {
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  } else if (camera.isOrthographicCamera) {
    const half = (camera.top - camera.bottom) / 2;
    const aspect = w / h;
    camera.left = -half * aspect; camera.right = half * aspect;
    camera.updateProjectionMatrix();
  }
}
new ResizeObserver(resize).observe(canvas);

// ============ Corner gizmo (XYZ triad mirroring camera) ============
const gScene = new THREE.Scene();
const gCam = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
gCam.up.set(0, 0, 1);
const gRend = new THREE.WebGLRenderer({ canvas: gizmoCanvas, antialias: true, alpha: true });
gRend.setSize(96, 96, false);
gRend.setPixelRatio(Math.min(window.devicePixelRatio, 2));

function gizmoAxisLabel(letter, hex) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const ctx = c.getContext('2d');
  ctx.font = 'bold 44px -apple-system, "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineWidth = 4;
  ctx.strokeText(letter, 32, 36);
  ctx.fillStyle = hex; ctx.fillText(letter, 32, 36);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthTest: false }));
  s.scale.set(0.42, 0.42, 0.42); s.renderOrder = 10;
  return s;
}

function makeGizmoAxis(dir, colHex, hex, label) {
  const g = new THREE.Group();
  g.add(new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), dir.clone().multiplyScalar(0.85)]),
    new THREE.LineBasicMaterial({ color: colHex })
  ));
  const tip = new THREE.Mesh(
    new THREE.ConeGeometry(0.09, 0.22, 16),
    new THREE.MeshBasicMaterial({ color: colHex })
  );
  tip.position.copy(dir.clone().multiplyScalar(0.96));
  tip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  g.add(tip);
  const lbl = gizmoAxisLabel(label, hex);
  lbl.position.copy(dir.clone().multiplyScalar(1.18));
  g.add(lbl);
  return g;
}
gScene.add(makeGizmoAxis(new THREE.Vector3(1, 0, 0), 0xe53935, '#c62828', 'X'));
gScene.add(makeGizmoAxis(new THREE.Vector3(0, 1, 0), 0x2e7d32, '#1b5e20', 'Y'));
gScene.add(makeGizmoAxis(new THREE.Vector3(0, 0, 1), 0x1565c0, '#0d47a1', 'Z'));

function renderGizmo() {
  const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
  gCam.position.copy(dir.multiplyScalar(3.4));
  gCam.up.copy(camera.up);
  gCam.lookAt(0, 0, 0);
  gRend.render(gScene, gCam);
}

// ============ Animate ============
function animate() {
  controls.update();
  renderer.render(scene, camera);
  renderGizmo();
  requestAnimationFrame(animate);
}
resize();
setView('iso');
animate();

// ============ Run pipeline ============
function setStatus(state, text, errText) {
  statusPill.className = 'pill ' + state;
  statusPill.textContent = state;
  statusText.textContent = text || '';
  errDetail.textContent = errText || '';
}

async function run() {
  setStatus('running', 'Compiling build123d code', '');
  elapsedEl.textContent = '';
  downloads.classList.remove('visible');
  statsCard.classList.remove('visible');
  consoleEl.classList.remove('visible');
  runBtn.disabled = true;
  loadingBar.classList.add('visible');
  try {
    const res = await fetch('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: promptInput.value, code: editor.value }),
    });
    const data = await res.json();
    elapsedEl.textContent = data.elapsed_ms ? `${data.elapsed_ms} ms` : '';
    if (!data.ok) {
      setStatus('err', data.error_type || 'Error', data.error || '');
      consoleHead.textContent = `${data.error_type}: ${data.error}`;
      const parts = [];
      if (data.stdout) parts.push('— stdout —\n' + data.stdout);
      if (data.traceback) parts.push('— traceback —\n' + data.traceback);
      if (data.available_vars) parts.push('available vars: ' + data.available_vars.join(', '));
      consoleBody.textContent = parts.join('\n\n');
      consoleEl.classList.add('visible');
      return;
    }
    dlGlb.href = data.glb_url; dlStep.href = data.step_url; dlStl.href = data.stl_url;
    downloads.classList.add('visible');

    const v = data.validation || {};
    document.getElementById('s-vol').textContent = (v.volume_mm3 ?? 0).toLocaleString() + ' mm³';
    if (v.bbox) {
      const s = v.bbox.size, c = v.bbox.center;
      document.getElementById('s-bbox').textContent = `${s[0]} × ${s[1]} × ${s[2]} mm`;
      document.getElementById('s-center').textContent = `${c[0]}, ${c[1]}, ${c[2]}`;
    }
    if (v.topology) {
      const t = v.topology;
      document.getElementById('s-topo').textContent = `${t.faces}F / ${t.edges}E / ${t.vertices}V`;
    }
    const wt = document.getElementById('s-wt');
    if (v.watertight === true)  { wt.textContent = 'yes'; wt.className = 'val ok'; }
    else if (v.watertight === false) { wt.textContent = 'no';  wt.className = 'val err'; }
    else                              { wt.textContent = '?';   wt.className = 'val'; }
    statsCard.classList.add('visible');

    setStatus('ok', 'Compiled successfully', '');
    await showModel(data.stl_url + '?t=' + Date.now());
  } catch (err) {
    setStatus('err', 'Request failed', err.message);
  } finally {
    runBtn.disabled = false;
    loadingBar.classList.remove('visible');
  }
}
runBtn.addEventListener('click', run);
</script>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
def health():
    return {"ok": True, "studio_dir": str(STUDIO_DIR)}


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 7860
    print(f"\n  OrionFlow Studio  ->  http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
