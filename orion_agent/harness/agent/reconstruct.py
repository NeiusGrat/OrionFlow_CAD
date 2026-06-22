"""Reconstruct-pillar verification: render-and-compare.

A reconstruction is only trustworthy if re-rendering it reproduces the input
drawing. This module supplies the comparison machinery:

  * dimensional divergence — does the built model's bounding box / feature set
    match the dimensions called out in the drawing,
  * pixel divergence — optional image difference between the rendered result and
    the source drawing (when both images exist and Pillow is available).

The pillar always surfaces a confidence/divergence number; a poor match is
reported honestly rather than emitting a confident-but-wrong model.

Note: k2v2 think is text-only, so the vision-extraction step degrades to
reading a textual dimension list. A VL model configured in the LLM layer would
restore full drawing ingest with no change here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TargetSpec:
    """What the drawing says the part should be (parsed from text/dims)."""

    dimensions: list[float] = field(default_factory=list)   # ordered overall dims
    holes: Optional[int] = None
    raw: str = ""


@dataclass
class ReconstructionScore:
    divergence: float            # 0 == perfect, 1 == fully wrong
    confidence: float            # 1 - divergence
    dimensional_match: bool
    detail: str = ""


_DIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?")


def parse_target(text: str) -> TargetSpec:
    """Extract overall dimensions and hole count from a textual drawing spec."""
    # Patterns like "60 x 40 x 5" or "60x40x5".
    dims: list[float] = []
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?",
                  text.lower())
    if m:
        dims = [float(g) for g in m.groups() if g]
    hm = re.search(r"(\d+)\s*(?:holes?|bores?)", text.lower())
    holes = int(hm.group(1)) if hm else None
    return TargetSpec(dimensions=dims, holes=holes, raw=text)


def score_reconstruction(result_topology: dict, target: TargetSpec,
                         tol: float = 0.02) -> ReconstructionScore:
    """Compare a built model's topology against the target spec."""
    bbox = (result_topology or {}).get("bounding_box", {}).get("size")
    components: list[float] = []
    detail_parts: list[str] = []

    if target.dimensions and bbox:
        got = sorted(bbox, reverse=True)
        want = sorted(target.dimensions, reverse=True)
        n = min(len(got), len(want))
        diffs = []
        for i in range(n):
            denom = want[i] if want[i] else 1.0
            diffs.append(abs(got[i] - want[i]) / denom)
        dim_div = sum(diffs) / len(diffs) if diffs else 1.0
        components.append(min(dim_div, 1.0))
        detail_parts.append(f"dims got={got} want={want} div={dim_div:.3f}")
    elif target.dimensions:
        components.append(1.0)
        detail_parts.append("no bbox in result")

    if target.holes is not None:
        got_holes = result_topology.get("cylindrical_faces", 0)
        hole_div = 0.0 if got_holes == target.holes else min(
            abs(got_holes - target.holes) / max(target.holes, 1), 1.0
        )
        components.append(hole_div)
        detail_parts.append(f"holes got={got_holes} want={target.holes}")

    divergence = sum(components) / len(components) if components else 1.0
    return ReconstructionScore(
        divergence=round(divergence, 4),
        confidence=round(1.0 - divergence, 4),
        dimensional_match=divergence <= tol,
        detail="; ".join(detail_parts),
    )


def image_divergence(path_a: str, path_b: str) -> Optional[float]:
    """Normalised pixel difference in [0,1] between two renders/drawings.

    Returns ``None`` if Pillow is unavailable or an image cannot be read.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    try:
        a = Image.open(path_a).convert("L").resize((256, 256))
        b = Image.open(path_b).convert("L").resize((256, 256))
    except Exception:  # noqa: BLE001
        return None
    import numpy as np

    arr_a = np.asarray(a, dtype="float32") / 255.0
    arr_b = np.asarray(b, dtype="float32") / 255.0
    return float(np.mean(np.abs(arr_a - arr_b)))
