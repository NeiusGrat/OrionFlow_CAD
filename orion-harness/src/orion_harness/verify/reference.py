"""Reference-based scorers (§7.4): Chamfer Distance, volumetric IoU, and
Invalidity Ratio, to the CAD-Recode/cadrille field convention so OrionFlow
numbers are comparable to published work. Optional per task
(TaskSpec.reference); never the default scorer -- gates (R2) and the
geometry-only tiers are what every task runs, this is an opt-in overlay
for cross-paper comparability, and the gNucleus-style similarity scorer
is one plug-in here among several, never the default (§7.4).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from build123d import export_stl
from scipy.spatial import cKDTree


def _to_trimesh(shape, tolerance: float = 0.1) -> trimesh.Trimesh:
    with tempfile.TemporaryDirectory(prefix="orion_harness_ref_") as d:
        path = Path(d) / "shape.stl"
        export_stl(shape, str(path), tolerance=tolerance)
        mesh = trimesh.load(str(path))
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(mesh.dump())
    return mesh


def normalize_to_unit_box(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh = mesh.copy()
    mesh.apply_translation(-mesh.bounding_box.centroid)
    extent = float(mesh.bounding_box.extents.max())
    scale = 1.0 / extent if extent > 1e-12 else 1.0
    mesh.apply_scale(scale)
    return mesh


def chamfer_distance(shape_a, shape_b, n_points: int = 8192, seed: int = 0) -> dict:
    """Symmetric Chamfer Distance, normalized to a unit box (§7.4).
    Reports mean and median -- invalid/degenerate outputs bias the mean,
    which is exactly why the field convention reports both."""

    mesh_a = normalize_to_unit_box(_to_trimesh(shape_a))
    mesh_b = normalize_to_unit_box(_to_trimesh(shape_b))

    pts_a, _ = trimesh.sample.sample_surface(mesh_a, n_points, seed=seed)
    pts_b, _ = trimesh.sample.sample_surface(mesh_b, n_points, seed=seed + 1)

    d_ab, _ = cKDTree(pts_b).query(pts_a)
    d_ba, _ = cKDTree(pts_a).query(pts_b)

    all_d = np.concatenate([d_ab, d_ba])
    return {
        "mean": float(all_d.mean()),
        "median": float(np.median(all_d)),
        "mean_a_to_b": float(d_ab.mean()),
        "mean_b_to_a": float(d_ba.mean()),
    }


def volumetric_iou(shape_a, shape_b) -> float:
    """Exact boolean IoU via OCCT booleans (build123d's `&` operator) --
    more accurate than a voxel/point approximation, and the two shapes
    are already B-reps, so there is no reason to approximate."""

    intersection_volume = float((shape_a & shape_b).volume)
    union_volume = float(shape_a.volume) + float(shape_b.volume) - intersection_volume
    if union_volume <= 0:
        return 0.0
    return intersection_volume / union_volume


def invalidity_ratio(statuses: list[str]) -> float:
    """§7.4: share of outputs that fail to produce valid geometry.
    Counts status in {"invalid", "timeout"} (parse_error, exec_crash,
    model_refusal, solver_result_implausible, exec_timeout -- §6.3: all
    of these mean no usable geometry came out) -- NOT a "scored" result
    that failed some semantic check with otherwise-valid geometry (that
    is a CD/IoU question, not an IR question), and excludes "error"
    (our own infra failures, R3)."""

    countable = [s for s in statuses if s != "error"]
    if not countable:
        return 0.0
    n_invalid = sum(1 for s in countable if s in ("invalid", "timeout"))
    return n_invalid / len(countable)
