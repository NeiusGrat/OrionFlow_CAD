"""Step 1 — fetch the gNucleus dataset into the structured ``data/`` layout.

System-Python side. Uses ``huggingface_hub`` + ``pyarrow`` (pandas is avoided:
it crashes on this machine's numpy2/numexpr mismatch).
"""

from __future__ import annotations

import shutil
from typing import Any

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from .config import (
    DATASET_REPO,
    EDGES_DIR,
    FCSTD_DIR,
    GLB_DIR,
    PARQUET_LOCAL,
    PARQUET_REMOTE,
    ensure_dirs,
)


def download_parquet() -> str:
    ensure_dirs()
    cached = hf_hub_download(DATASET_REPO, PARQUET_REMOTE, repo_type="dataset")
    shutil.copy(cached, PARQUET_LOCAL)
    return str(PARQUET_LOCAL)


def load_rows(limit: int | None = None) -> list[dict[str, Any]]:
    """Read the parquet (downloading if needed) into plain dicts.

    The heavy ``image`` column is dropped — extraction never needs it.
    """
    if not PARQUET_LOCAL.exists():
        download_parquet()
    table = pq.read_table(PARQUET_LOCAL)
    cols = [c for c in table.column_names if c != "image"]
    rows = table.select(cols).to_pylist()
    return rows[:limit] if limit else rows


def _fetch_to(remote: str, dest) -> bool:
    try:
        cached = hf_hub_download(DATASET_REPO, remote, repo_type="dataset")
        shutil.copy(cached, dest)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  WARN could not fetch {remote}: {e}")
        return False


def download_assets(rows: list[dict[str, Any]], with_glb: bool = False) -> dict[str, int]:
    """Download FCStd (+ edges, optional glb) for the given rows."""
    ensure_dirs()
    stats = {"fcstd": 0, "edges": 0, "glb": 0}
    for r in rows:
        rid = r["id"]
        fcstd_remote = r.get("fcstd_path") or f"fcstd/{rid}.FCStd"
        fcstd_dest = FCSTD_DIR / f"{rid}.FCStd"
        if fcstd_dest.exists() or _fetch_to(fcstd_remote, fcstd_dest):
            stats["fcstd"] += 1
        edges_dest = EDGES_DIR / f"{rid}_edges.json"
        if edges_dest.exists() or _fetch_to(f"edges/{rid}_edges.json", edges_dest):
            stats["edges"] += 1
        if with_glb:
            glb_dest = GLB_DIR / f"{rid}.glb"
            if glb_dest.exists() or _fetch_to(f"glb/{rid}.glb", glb_dest):
                stats["glb"] += 1
    return stats


if __name__ == "__main__":
    rows = load_rows()
    print(f"parquet rows: {len(rows)}")
    st = download_assets(rows)
    print("downloaded:", st)
