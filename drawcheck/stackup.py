"""One-dimensional tolerance stack-up: worst case and RSS.

A chain is a loop of dimensions around the gap you care about, each with a
direction (+1 adds to the gap, -1 takes from it). Asymmetric tolerances are
converted to a mean dimension with an equal-bilateral tolerance first, which
is the standard way to keep both methods correct.

    from drawcheck.stackup import Link, stack
    stack([Link(50, 0.1, -0.1, +1), Link(49.8, 0.05, -0.05, -1)], min_gap=0.0)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .parse import parse_dimension


@dataclass
class Link:
    nominal: float
    upper: float
    lower: float
    direction: int = 1
    label: str = ""

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        if self.upper < self.lower:
            raise ValueError(f"{self.label or self.nominal}: upper deviation below lower deviation")

    @property
    def mean(self) -> float:
        return self.nominal + (self.upper + self.lower) / 2

    @property
    def half(self) -> float:
        return (self.upper - self.lower) / 2


@dataclass
class StackResult:
    nominal: float
    mean: float
    worst_case_tol: float
    rss_tol: float
    wc_min: float
    wc_max: float
    rss_min: float
    rss_max: float
    min_gap: float | None
    max_gap: float | None
    wc_ok: bool | None
    rss_ok: bool | None
    contributors: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def stack(links: list[Link], min_gap: float | None = None, max_gap: float | None = None) -> StackResult:
    if not links:
        raise ValueError("empty chain")
    nominal = sum(k.direction * k.nominal for k in links)
    mean = sum(k.direction * k.mean for k in links)
    wc = sum(k.half for k in links)
    rss = math.sqrt(sum(k.half ** 2 for k in links))
    total_sq = sum(k.half ** 2 for k in links) or 1.0

    def ok(lo: float, hi: float) -> bool | None:
        if min_gap is None and max_gap is None:
            return None
        return (min_gap is None or lo >= min_gap - 1e-12) and (max_gap is None or hi <= max_gap + 1e-12)

    contributors = sorted(
        ({"label": k.label or f"{k.nominal}", "direction": k.direction, "half_tol": round(k.half, 6),
          "share_rss": round(k.half ** 2 / total_sq, 4)} for k in links),
        key=lambda c: -c["share_rss"],
    )
    r = lambda x: round(x, 6)  # noqa: E731
    return StackResult(
        nominal=r(nominal), mean=r(mean), worst_case_tol=r(wc), rss_tol=r(rss),
        wc_min=r(mean - wc), wc_max=r(mean + wc), rss_min=r(mean - rss), rss_max=r(mean + rss),
        min_gap=min_gap, max_gap=max_gap,
        wc_ok=ok(mean - wc, mean + wc), rss_ok=ok(mean - rss, mean + rss),
        contributors=contributors,
    )


def link_from_text(text: str) -> Link:
    """'+50 ±0.1', '-20 +0.05/0', '- 29.8 h7' is NOT accepted (fits need ISO 286 tables)."""
    t = text.strip()
    direction = 1
    if t[:1] in "+-":
        direction = 1 if t[0] == "+" else -1
        t = t[1:].strip()
    d = parse_dimension(t)
    if d is None or d["upper"] is None or d["lower"] is None:
        raise ValueError(f"cannot use '{text}' in a stack: give a nominal with explicit tolerance")
    return Link(d["nominal"], d["upper"], d["lower"], direction, label=t)
