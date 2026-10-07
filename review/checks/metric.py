"""Metric coarse fastener sizes, read as ranges.

A hole is a *clearance* hole for size S anywhere from just over S's nominal
diameter to just over the ISO 273 coarse series (designers use in-between
values: M3 through 3.3 is common); a *tap* hole within 0.15 mm of the ISO 2306
tap drill (printed parts shift it); a *nominal* hole within 0.05 mm of S itself
(CAD often draws a threaded hole at full size). A pair of mating holes is
compatible when the two share a size.

Values come from interface_check.rules.fasteners.METRIC (ISO 273 / ISO 2306).
"""
from __future__ import annotations

from interface_check.rules.fasteners import METRIC

TAP_TOL = 0.15
NOMINAL_TOL = 0.05
COARSE_SLACK = 0.1


def kinds(d: float) -> set[tuple[str, str]]:
    out = set()
    for size, (nominal, tap, fine, medium, coarse) in METRIC.items():
        if abs(d - nominal) <= NOMINAL_TOL:
            out.add((size, "nominal"))
        if abs(d - tap) <= TAP_TOL:
            out.add((size, "tap"))
        if nominal + NOMINAL_TOL < d <= coarse + COARSE_SLACK:
            out.add((size, "clearance"))
    return out


def sizes(d: float) -> set[str]:
    return {s for s, _ in kinds(d)}


def is_clearance_only(d: float) -> bool:
    """A hole that can only be a clearance hole (not a tap or nominal threaded hole)."""
    k = kinds(d)
    return bool(k) and all(kind == "clearance" for _, kind in k)


def compatible(stack1: list[float], stack2: list[float]) -> bool | None:
    """Any diameter of one stack shares a size with any of the other. None if neither stack is recognised."""
    s1 = set().union(*[sizes(d) for d in stack1]) if stack1 else set()
    s2 = set().union(*[sizes(d) for d in stack2]) if stack2 else set()
    if not s1 or not s2:
        return None
    return bool(s1 & s2)


def describe(stack: list[float]) -> str:
    parts = []
    for d in stack:
        k = sorted(kinds(d))
        parts.append(f"Ø{d:.2f}" + (" (" + ", ".join(f"{kind} {size}" for size, kind in k) + ")" if k else " (no metric size)"))
    return " over ".join(parts)


def sizes_of(stack: list[float]) -> set[str]:
    return set().union(*[sizes(d) for d in stack]) if stack else set()
