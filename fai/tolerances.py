"""Tolerance tables: ISO 2768-1 general tolerances and ISO 286-2 fits.

Only what can be looked up exactly is answered. A size or class outside these
tables returns ``None`` and the caller reports the characteristic as needing a
tolerance, rather than inventing one.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ ISO 2768-1

#: Linear dimensions: (upper bound of the size range in mm, {class: ± mm}).
#: The first range starts at 0.5 mm; below that ISO 2768 gives no value.
_LINEAR = [
    (3, {"f": 0.05, "m": 0.1, "c": 0.2}),
    (6, {"f": 0.05, "m": 0.1, "c": 0.3, "v": 0.5}),
    (30, {"f": 0.1, "m": 0.2, "c": 0.5, "v": 1.0}),
    (120, {"f": 0.15, "m": 0.3, "c": 0.8, "v": 1.5}),
    (400, {"f": 0.2, "m": 0.5, "c": 1.2, "v": 2.5}),
    (1000, {"f": 0.3, "m": 0.8, "c": 2.0, "v": 4.0}),
    (2000, {"f": 0.5, "m": 1.2, "c": 3.0, "v": 6.0}),
    (4000, {"m": 2.0, "c": 4.0, "v": 8.0}),
]
#: External radii and chamfer heights.
_RADIUS = [(3, {"f": 0.2, "m": 0.2, "c": 0.4, "v": 0.4}),
           (6, {"f": 0.5, "m": 0.5, "c": 1.0, "v": 1.0}),
           (1e9, {"f": 1.0, "m": 1.0, "c": 2.0, "v": 2.0})]
#: Angles, by the length of the shorter leg (mm): ± degrees.
_ANGULAR = [(10, {"f": 1.0, "m": 1.0, "c": 1.5, "v": 3.0}),
            (50, {"f": 0.5, "m": 0.5, "c": 1.0, "v": 2.0}),
            (120, {"f": 1 / 3, "m": 1 / 3, "c": 0.5, "v": 1.0}),
            (400, {"f": 1 / 6, "m": 1 / 6, "c": 0.25, "v": 0.5}),
            (1e9, {"f": 1 / 12, "m": 1 / 12, "c": 1 / 6, "v": 1 / 3})]

GENERAL_CLASSES = {"f": "fine", "m": "medium", "c": "coarse", "v": "very coarse"}


def _lookup(table, size: float, cls: str) -> float | None:
    for upper, row in table:
        if size <= upper:
            return row.get(cls)
    return None


def general_linear(nominal: float, cls: str) -> float | None:
    if nominal < 0.5:
        return None
    return _lookup(_LINEAR, nominal, cls)


def general_radius(nominal: float, cls: str) -> float | None:
    if nominal < 0.5:
        return None
    return _lookup(_RADIUS, nominal, cls)


def general_angle(cls: str, shorter_leg_mm: float | None = None) -> float | None:
    """± degrees. Without the leg length the tightest-leg row (≤10 mm) is used."""
    return _lookup(_ANGULAR, shorter_leg_mm if shorter_leg_mm else 1.0, cls)


# ------------------------------------------------------------------ ISO 286-2

_RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]
#: Standard tolerance grades, µm, per size range above.
_IT = {
    5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
}
#: Shaft fundamental deviations, µm: upper deviation (es) for f/g/h,
#: lower deviation (ei) for k (grades 4-7), n, p.
_SHAFT_ES = {
    "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h": [0] * 13,
}
_SHAFT_EI = {
    "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],
    "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
}
_FIT = re.compile(r"^(?P<letter>[A-Za-z]{1,2})(?P<grade>\d{1,2})$")


def _range_index(size: float) -> int | None:
    if size <= 0 or size > _RANGES[-1]:
        return None
    for i, upper in enumerate(_RANGES):
        if size <= upper:
            return i
    return None


def fit_limits(nominal: float, fit: str) -> tuple[float, float] | None:
    """(lower, upper) deviation in mm for one ISO 286 class, e.g. 'H7' or 'g6'.

    Covered: holes F G H JS, shafts f g h js k n p, grades IT5-IT11, sizes up
    to 500 mm. Anything else returns ``None`` (look it up, don't guess).
    """
    m = _FIT.match(fit.strip())
    i = _range_index(nominal)
    if not m or i is None:
        return None
    letter, grade = m.group("letter"), int(m.group("grade"))
    if grade not in _IT:
        return None
    it = _IT[grade][i]
    if letter in ("JS", "js"):
        return (-it / 2000, it / 2000)
    if letter.isupper():                      # holes: F, G, H are mirror images of f, g, h
        shaft = letter.lower()
        if shaft not in _SHAFT_ES or len(letter) != 1:
            return None
        ei = -_SHAFT_ES[shaft][i]
        return (ei / 1000, (ei + it) / 1000)
    if letter in _SHAFT_ES:
        es = _SHAFT_ES[letter][i]
        return ((es - it) / 1000, es / 1000)
    if letter in _SHAFT_EI:
        if letter == "k" and not 4 <= grade <= 7:
            return None
        ei = _SHAFT_EI[letter][i]
        return (ei / 1000, (ei + it) / 1000)
    return None
