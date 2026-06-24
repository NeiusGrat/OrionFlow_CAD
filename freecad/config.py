"""Shared paths and the FreeCAD-interpreter locator.

Importable from *both* the system Python and FreeCAD's Python (no third-party
imports here on the FreeCAD side).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo / pipeline layout
# ---------------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent          # .../freecad
REPO_ROOT = PKG_DIR.parent                          # .../OrionFLow_CAD

DATA_DIR = PKG_DIR / "data"
PARQUET_DIR = DATA_DIR / "parquet"
FCSTD_DIR = DATA_DIR / "fcstd"
GLB_DIR = DATA_DIR / "glb"
EDGES_DIR = DATA_DIR / "edges"

RAW_EXTRACT_DIR = PKG_DIR / "raw_extract"           # one <id>.json per FCStd
TRAINING_DIR = PKG_DIR / "training"                 # sample_XXXX.json + dataset.jsonl
SCHEMA_PATH = PKG_DIR / "feature_graph_schema.json"

DATASET_REPO = "gnucleus-ai/cad-gen-freecad"
PARQUET_REMOTE = "data/dataset.parquet"
PARQUET_LOCAL = PARQUET_DIR / "dataset.parquet"

SCHEMA_VERSION = "ofl_fcstd_v1"

# Object TypeIds that are PartDesign/Origin boilerplate (kept out of features).
BOILERPLATE_TYPES = {
    "App::Origin",
    "App::Line",
    "App::Plane",
    "App::Point",
    "App::DocumentObjectGroup",
}


def ensure_dirs() -> None:
    for d in (PARQUET_DIR, FCSTD_DIR, GLB_DIR, EDGES_DIR, RAW_EXTRACT_DIR, TRAINING_DIR):
        d.mkdir(parents=True, exist_ok=True)


def find_freecad_python() -> str:
    """Locate a Python interpreter that can ``import FreeCAD``.

    Resolution order:
      1. ``$ORION_FREECAD_PYTHON`` env override
      2. ``freecadcmd`` / ``FreeCADCmd`` on PATH
      3. Known Windows install dirs (``C:/Program Files/FreeCAD */bin/python.exe``)
    """
    env = os.environ.get("ORION_FREECAD_PYTHON")
    if env and Path(env).exists():
        return env

    for name in ("freecadcmd", "FreeCADCmd", "freecadcmd.exe"):
        found = shutil.which(name)
        if found:
            return found

    candidates: list[Path] = []
    for base in (r"C:/Program Files", r"C:/Program Files (x86)"):
        b = Path(base)
        if b.exists():
            for d in sorted(b.glob("FreeCAD*"), reverse=True):
                for exe in ("bin/python.exe", "bin/freecadcmd.exe"):
                    p = d / exe
                    if p.exists():
                        candidates.append(p)
    if candidates:
        return str(candidates[0])

    raise RuntimeError(
        "Could not locate a FreeCAD Python interpreter. Set ORION_FREECAD_PYTHON "
        "to FreeCAD's python.exe or freecadcmd.exe."
    )
