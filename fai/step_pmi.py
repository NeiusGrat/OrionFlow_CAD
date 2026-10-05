"""AP242 semantic PMI, read straight from the STEP text: the answer key.

OpenCASCADE's GD&T reader drops tolerance magnitudes on some AP242 files (every
zone came back 0.0 on NIST FTC 08) and mixes units, so this module parses the
Part 21 entities itself — the same entities NIST's STEP File Analyzer reports:

    DIMENSIONAL_SIZE / DIMENSIONAL_LOCATION      what a dimension is
    DIMENSIONAL_CHARACTERISTIC_REPRESENTATION    -> SHAPE_DIMENSION_REPRESENTATION (its value)
    PLUS_MINUS_TOLERANCE -> TOLERANCE_VALUE      its +/- limits
    <X>_TOLERANCE (+ GEOMETRIC_TOLERANCE...)     a geometric tolerance and its zone
    DATUM_SYSTEM -> DATUM_REFERENCE_COMPARTMENT -> DATUM   its datum references
    TOLERANCE_ZONE -> TOLERANCE_ZONE_FORM        'cylindrical or circular' = Ø zone
    CONVERSION_BASED_UNIT / SI_UNIT              units (inch parts are converted)

Every length is returned twice: in millimetres and in the file's own unit, so
it can be compared with a drawing printed in either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GDT_ENTITIES = {
    "ANGULARITY_TOLERANCE": "angularity", "CIRCULAR_RUNOUT_TOLERANCE": "circular_runout",
    "COAXIALITY_TOLERANCE": "concentricity", "CONCENTRICITY_TOLERANCE": "concentricity",
    "CYLINDRICITY_TOLERANCE": "cylindricity", "FLATNESS_TOLERANCE": "flatness",
    "LINE_PROFILE_TOLERANCE": "profile_line", "PARALLELISM_TOLERANCE": "parallelism",
    "PERPENDICULARITY_TOLERANCE": "perpendicularity", "POSITION_TOLERANCE": "position",
    "ROUNDNESS_TOLERANCE": "circularity", "STRAIGHTNESS_TOLERANCE": "straightness",
    "SURFACE_PROFILE_TOLERANCE": "profile_surface", "SYMMETRY_TOLERANCE": "symmetry",
    "TOTAL_RUNOUT_TOLERANCE": "total_runout",
}
SIZE_TYPES = {"diameter": "Diameter", "radius": "Radius", "spherical diameter": "Diameter",
              "spherical radius": "Radius", "thickness": "Linear", "curve length": "Linear",
              "angular": "Angle", "angle": "Angle"}


# ------------------------------------------------------------------ Part 21 parsing

@dataclass
class Ref:
    id: int


@dataclass
class Typed:
    name: str
    args: list


@dataclass
class Enum:
    value: str


_TOKEN = re.compile(r"""
    (?P<str>'(?:[^']|'')*')
  | (?P<ref>\#\d+)
  | (?P<enum>\.[A-Z_][A-Z0-9_]*\.)
  | (?P<num>[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?)
  | (?P<kw>[A-Z_][A-Z0-9_]*)
  | (?P<punct>[(),$*])
""", re.X)


def _tokens(text: str):
    for m in _TOKEN.finditer(text):
        k = m.lastgroup
        v = m.group(k)
        yield k, v


def _parse_value(toks, i):
    k, v = toks[i]
    if k == "str":
        return v[1:-1].replace("''", "'"), i + 1
    if k == "ref":
        return Ref(int(v[1:])), i + 1
    if k == "enum":
        return Enum(v.strip(".")), i + 1
    if k == "num":
        return float(v), i + 1
    if k == "punct" and v in "$*":
        return None, i + 1
    if k == "punct" and v == "(":
        return _parse_list(toks, i)
    if k == "kw":
        if i + 1 < len(toks) and toks[i + 1] == ("punct", "("):
            args, j = _parse_list(toks, i + 1)
            return Typed(v, args), j
        return v, i + 1
    raise ValueError(f"unexpected token {v!r}")


def _parse_list(toks, i):
    assert toks[i] == ("punct", "(")
    i += 1
    out = []
    while toks[i] != ("punct", ")"):
        if toks[i] == ("punct", ","):
            i += 1
            continue
        v, i = _parse_value(toks, i)
        out.append(v)
    return out, i + 1


def parse_entities(text: str) -> dict[int, list[Typed]]:
    """{id: [Typed, ...]} — one Typed for a simple entity, several for a complex one."""
    data = text[text.find("DATA;") + 5: text.rfind("ENDSEC;")] if "DATA;" in text else text
    out: dict[int, list[Typed]] = {}
    for stmt in _statements(data):
        m = re.match(r"\s*#(\d+)\s*=\s*(.*)$", stmt, re.S)
        if not m:
            continue
        eid, body = int(m.group(1)), m.group(2).strip()
        if not body.startswith("(") and not re.match(r"[A-Z_]", body):
            continue
        # Only PMI-relevant entities are worth a full parse; geometry is skipped.
        if not _INTEREST.search(body):
            continue
        try:
            toks = list(_tokens(body))
            if body.startswith("("):
                parts, i = [], 1
                while toks[i] != ("punct", ")"):
                    v, i = _parse_value(toks, i)
                    if isinstance(v, Typed):
                        parts.append(v)
                out[eid] = parts
            else:
                v, _ = _parse_value(toks, 0)
                out[eid] = [v] if isinstance(v, Typed) else []
        except (ValueError, IndexError, AssertionError):
            continue
    return out


_INTEREST = re.compile(r"TOLERANCE|DIMENSION|DATUM|MEASURE|UNIT|SHAPE_ASPECT|REPRESENTATION_ITEM")


def _statements(data: str):
    buf, in_str = [], False
    start = 0
    for i, ch in enumerate(data):
        if ch == "'":
            in_str = not in_str
        elif ch == ";" and not in_str:
            yield data[start:i]
            start = i + 1


# ------------------------------------------------------------------ interpretation

class _Model:
    def __init__(self, ents: dict[int, list[Typed]]):
        self.e = ents

    def parts(self, ref) -> list[Typed]:
        return self.e.get(ref.id, []) if isinstance(ref, Ref) else []

    def part(self, ref, name: str) -> Typed | None:
        return next((p for p in self.parts(ref) if p.name == name), None)

    def names(self, eid: int) -> set[str]:
        return {p.name for p in self.e.get(eid, [])}

    def unit_factor(self, ref) -> tuple[float, str]:
        """(factor to mm or degrees, unit label)."""
        ps = self.parts(ref)
        names = {p.name for p in ps}
        for p in ps:
            if p.name == "CONVERSION_BASED_UNIT" and p.args and isinstance(p.args[0], str):
                n = p.args[0].upper()
                if "INCH" in n:
                    return 25.4, "in"
                if "FOOT" in n:
                    return 304.8, "ft"
                if "DEGREE" in n:
                    return 1.0, "deg"
            if p.name == "SI_UNIT":
                prefix = p.args[0].value if p.args and isinstance(p.args[0], Enum) else None
                base = p.args[1].value if len(p.args) > 1 and isinstance(p.args[1], Enum) else ""
                if base == "METRE":
                    return {"MILLI": 1.0, "CENTI": 10.0, None: 1000.0, "MICRO": 0.001}.get(prefix, 1.0), "mm"
                if base == "RADIAN":
                    return 57.29577951308232, "deg"
        if "LENGTH_UNIT" in names:
            return 1.0, "mm"
        return 1.0, ""

    def measure(self, ref) -> tuple[float | None, float, str, str]:
        """(value in mm/deg, factor, file unit, qualifier name) of a measure entity."""
        for p in self.parts(ref):
            if p.name.endswith("MEASURE_WITH_UNIT") and len(p.args) >= 2 and isinstance(p.args[0], Typed):
                raw = p.args[0].args[0] if p.args[0].args else None
                f, unit = self.unit_factor(p.args[1])
                if isinstance(raw, float):
                    qual = next((q.args[0] for q in self.parts(ref)
                                 if q.name == "REPRESENTATION_ITEM" and q.args and isinstance(q.args[0], str)), "")
                    return raw * f, f, unit, qual
        return None, 1.0, "", ""


def read(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="latin-1", errors="replace")
    m = _Model(parse_entities(text))
    out = {"source": Path(path).name, "schema": _schema(text), "dimensions": [], "gdt": [], "datums": [],
           "units": None}

    # datum letters
    letters: dict[int, str] = {}
    for eid, ps in m.e.items():
        for p in ps:
            if p.name == "DATUM" and len(p.args) >= 5 and isinstance(p.args[4], str):
                letters[eid] = p.args[4]
    out["datums"] = sorted(set(letters.values()))

    # dimensions: characteristic representation links a dimension to its value
    tol_of: dict[int, tuple] = {}
    for eid, ps in m.e.items():
        for p in ps:
            if p.name == "PLUS_MINUS_TOLERANCE" and len(p.args) >= 2 and isinstance(p.args[1], Ref):
                tv = m.part(p.args[0], "TOLERANCE_VALUE")
                if tv and len(tv.args) >= 2:
                    lo = m.measure(tv.args[0])[0]
                    hi = m.measure(tv.args[1])[0]
                    tol_of[p.args[1].id] = (lo, hi)
    for eid, ps in m.e.items():
        for p in ps:
            if p.name != "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION" or len(p.args) < 2:
                continue
            dim_ref, rep_ref = p.args[0], p.args[1]
            dim_parts = m.parts(dim_ref)
            kind, typ = "location", "Linear"
            for dp in dim_parts:
                if dp.name.startswith("DIMENSIONAL_SIZE") and len(dp.args) >= 2 and isinstance(dp.args[1], str):
                    kind, typ = "size", SIZE_TYPES.get(dp.args[1].lower(), "Linear")
                elif dp.name.startswith(("DIMENSIONAL_LOCATION", "ANGULAR_LOCATION")):
                    name = dp.args[0] if dp.args and isinstance(dp.args[0], str) else ""
                    kind, typ = "location", "Angle" if "angular" in (name.lower() + dp.name.lower()) else "Linear"
            rep = m.part(rep_ref, "SHAPE_DIMENSION_REPRESENTATION")
            if rep is None or len(rep.args) < 2:
                continue
            values = [m.measure(item) for item in (rep.args[1] or []) if isinstance(item, Ref)]
            values = [v for v in values if v[0] is not None]
            if not values:
                continue
            nominal = next((v for v in values if "nominal" in v[3].lower()), None)
            upper = next((v for v in values if "upper" in v[3].lower()), None)
            lower = next((v for v in values if "lower" in v[3].lower()), None)
            nominal = nominal or values[0]
            unit = nominal[2]
            out["units"] = out["units"] or (unit if unit in ("in", "mm") else None)
            lo = hi = None
            if isinstance(dim_ref, Ref) and dim_ref.id in tol_of:
                lo, hi = tol_of[dim_ref.id]
            elif upper and lower:
                lo, hi = lower[0] - nominal[0], upper[0] - nominal[0]
            f = nominal[1] if typ != "Angle" else 1.0
            out["dimensions"].append({
                "type": typ, "kind": kind, "unit": unit if typ != "Angle" else "deg",
                "nominal_mm": round(nominal[0], 6), "nominal": round(nominal[0] / f, 6),
                "lower": None if lo is None else round(lo / f, 6), "upper": None if hi is None else round(hi / f, 6),
            })

    # geometric tolerances
    zone_dia: set[int] = set()
    for eid, ps in m.e.items():
        for p in ps:
            if p.name == "TOLERANCE_ZONE" and len(p.args) >= 6:
                form = m.part(p.args[5], "TOLERANCE_ZONE_FORM")
                if form and form.args and "cylindrical" in str(form.args[0]).lower():
                    for t in p.args[4] or []:
                        if isinstance(t, Ref):
                            zone_dia.add(t.id)
    for eid, ps in m.e.items():
        names = {p.name for p in ps}
        kind = next((GDT_ENTITIES[n] for n in names if n in GDT_ENTITIES), None)
        if not kind:
            continue
        base = next((p for p in ps if p.name in ("GEOMETRIC_TOLERANCE",) or p.name in GDT_ENTITIES and p.args), None)
        if base is None or len(base.args) < 3:
            continue
        mag, f, unit, _ = m.measure(base.args[2])
        datum_refs: list = []
        for p in ps:
            if p.name == "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE" and p.args:
                datum_refs = p.args[0] or []
            elif p.name in GDT_ENTITIES and len(p.args) >= 5 and isinstance(p.args[4], list):
                datum_refs = p.args[4]
        datums = []
        for ds in datum_refs:
            sysp = m.part(ds, "DATUM_SYSTEM")
            comps = sysp.args[4] if sysp and len(sysp.args) >= 5 else []
            for c in comps or []:
                comp = m.part(c, "DATUM_REFERENCE_COMPARTMENT")
                if comp and len(comp.args) >= 5:
                    base_ref = comp.args[4]
                    if isinstance(base_ref, Ref) and base_ref.id in letters:
                        datums.append(letters[base_ref.id])
                    elif isinstance(base_ref, Typed):     # COMMON_DATUM_LIST((#a,#b)) of DATUM_REFERENCE_ELEMENTs
                        common = []
                        for r in (base_ref.args[0] if base_ref.args else []):
                            if not isinstance(r, Ref):
                                continue
                            el = m.part(r, "DATUM_REFERENCE_ELEMENT")
                            target = el.args[4] if el and len(el.args) >= 5 else r
                            common.append(letters.get(target.id, "?") if isinstance(target, Ref) else "?")
                        datums.append("-".join(common))
        mods = []
        for p in ps:
            if p.name in ("GEOMETRIC_TOLERANCE_WITH_MODIFIERS", "GEOMETRIC_TOLERANCE_WITH_MAXIMUM_TOLERANCE") and p.args:
                mods += [x.value for x in (p.args[0] or []) if isinstance(x, Enum)]
        material = "M" if "MAXIMUM_MATERIAL_REQUIREMENT" in mods else "L" if "LEAST_MATERIAL_REQUIREMENT" in mods else None
        if mag is None:
            continue
        out["units"] = out["units"] or (unit if unit in ("in", "mm") else None)
        out["gdt"].append({"type": kind, "tolerance_mm": round(mag, 6), "tolerance": round(mag / f, 6), "unit": unit,
                           "diameter_zone": eid in zone_dia, "material": material, "datums": datums})
    return out


def _schema(text: str) -> str:
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    return m.group(1) if m else ""
