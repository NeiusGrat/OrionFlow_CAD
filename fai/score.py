"""Score the drawing reader against the model's semantic PMI (the answer key).

Each PMI item is one row:
    matched   a characteristic with the same kind, value and tolerance was read
    partial   the value was read but the tolerance (or GD&T symbol / datums) differs
    missed    nothing on the drawing was read for it
Drawing characteristics that match no PMI item are counted as ``extra``
(a misread, or an annotation the model does not carry, such as a note).

Everything is compared in millimetres, so an inch drawing scores against an
inch model and a metric one against a metric model without assumptions.
"""
from __future__ import annotations

_DIM_CLASS = {"Diameter": "Diameter", "Radius": "Radius", "Angle": "Angle", "Linear": "Linear", "Basic": "Linear"}
_GDT_NAME = {"Flatness": "flatness", "Straightness": "straightness", "Circularity": "circularity",
             "Cylindricity": "cylindricity", "Profile of a line": "profile_line",
             "Profile of a surface": "profile_surface", "Perpendicularity": "perpendicularity",
             "Parallelism": "parallelism", "Angularity": "angularity", "Position": "position",
             "Concentricity": "concentricity", "Symmetry": "symmetry", "Circular runout": "circular_runout",
             "Total runout": "total_runout"}


def _k(unit: str) -> float:
    return 25.4 if unit == "in" else 1.0


def _close(a, b, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def score(chars: list[dict], key: dict) -> dict:
    dims = [c for c in chars if c["kind"] == "dimension" and c.get("nominal") is not None]
    gdts = [c for c in chars if c["kind"] == "gdt"]
    budget = {c["no"]: max(1, c.get("count") or 1) for c in dims + gdts}   # a "4X" callout covers 4 PMI items
    used: dict[int, int] = {}
    rows = []

    for d in key.get("dimensions", []):
        k = _k(d["unit"]) if d["type"] != "Angle" else 1.0
        nominal_mm = d["nominal"] * k
        lo_mm = None if d["lower"] is None else d["lower"] * k
        hi_mm = None if d["upper"] is None else d["upper"] * k
        best, status = None, "missed"
        for c in dims:
            if used.get(c["no"], 0) >= budget[c["no"]]:
                continue
            if _DIM_CLASS.get(c["type"], c["type"]) != d["type"] and not (d["type"] == "Linear" and c["type"] == "Basic"):
                continue
            ck = _k(c.get("unit", "mm")) if c["type"] != "Angle" else 1.0
            # a drawing prints its value rounded (".594" for .5938): allow half a unit in the last digit
            if not _close(c["nominal"] * ck, nominal_mm, max(1e-3, _half_unit(c["designator"]) * ck)):
                continue
            c_lo = None if c.get("tol_minus") is None else c["tol_minus"] * ck
            c_hi = None if c.get("tol_plus") is None else c["tol_plus"] * ck
            tol_ok = (lo_mm is None and hi_mm is None) or (_close(c_lo, lo_mm, 1e-3) and _close(c_hi, hi_mm, 1e-3))
            st = "matched" if tol_ok else "partial"
            if best is None or (st == "matched" and status != "matched"):
                best, status = c, st
                if st == "matched":
                    break
        if best is not None:
            used[best["no"]] = used.get(best["no"], 0) + 1
        rows.append({"kind": "dimension", "status": status, "char_no": best["no"] if best else None,
                     "key": _dim_text(d), "read": best["designator"] if best else ""})

    for g in key.get("gdt", []):
        k = _k(g["unit"])
        tol_mm = g["tolerance"] * k
        best, status, rank = None, "missed", None
        want = [x for x in g["datums"] if x]
        for c in gdts:
            if used.get(c["no"], 0) >= budget[c["no"]]:
                continue
            ck = _k(c.get("unit", "mm"))
            if c.get("upper") is None or not _close(c["upper"] * ck, tol_mm, 1e-3):
                continue
            same_datums = _datums(c["requirement"]) == want
            symbol_ok = _GDT_NAME.get(c["type"]) == g["type"]
            r = (same_datums and symbol_ok, same_datums, symbol_ok)
            if rank is None or r > rank:
                best, rank = c, r
                status = "matched" if r[0] else "partial"
        if best is not None:
            used[best["no"]] = used.get(best["no"], 0) + 1
        rows.append({"kind": "gdt", "status": status, "char_no": best["no"] if best else None,
                     "key": _gdt_text(g), "read": best["designator"] if best else ""})

    extra = [c["no"] for c in dims + gdts if c["no"] not in used and c.get("inspect", True)]
    total = len(rows)
    matched = sum(r["status"] == "matched" for r in rows)
    partial = sum(r["status"] == "partial" for r in rows)
    read_items = len([c for c in dims + gdts if c.get("inspect", True)])
    return {
        "key_source": key.get("source", ""), "key_schema": key.get("schema", ""), "total": total,
        "matched": matched, "partial": partial, "missed": total - matched - partial, "extra": extra,
        "recall": round(matched / total, 4) if total else None,
        "recall_with_partial": round((matched + partial) / total, 4) if total else None,
        "precision": round((read_items - len(extra)) / read_items, 4) if read_items else None,
        "rows": rows,
    }


def _half_unit(designator: str) -> float:
    """Half a unit in the last printed decimal of the callout's first number (".594" -> 0.0005)."""
    import re

    m = re.search(r"(\d*)\.(\d+)", designator)
    return 0.5 * 10 ** -len(m.group(2)) + 1e-9 if m else 0.5


def _datums(requirement: str) -> list[str]:
    import re

    m = re.search(r"to datums ([A-Z\-]+)", requirement)
    return m.group(1).split("-") if m else []


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s or "0"


def _dim_text(d: dict) -> str:
    sym = {"Diameter": "Ø", "Radius": "R", "Angle": "", "Linear": ""}[d["type"]]
    tol = ""
    if d["lower"] is not None and d["upper"] is not None:
        tol = (f" ±{_fmt(d['upper'])}" if abs(d["upper"] + d["lower"]) < 1e-9
               else f" +{_fmt(d['upper'])}/-{_fmt(abs(d['lower']))}")
    return f"{sym}{_fmt(d['nominal'])}{'°' if d['type'] == 'Angle' else ''}{tol}"


def _gdt_text(g: dict) -> str:
    zone = ("Ø" if g["diameter_zone"] else "") + _fmt(g["tolerance"]) + ({"M": " Ⓜ", "L": " Ⓛ"}.get(g["material"]) or "")
    datums = " ".join(x for x in g["datums"] if x)
    return f"{g['type'].replace('_', ' ')} {zone}{(' | ' + datums) if datums else ''}"
