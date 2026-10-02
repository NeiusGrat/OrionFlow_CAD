"""Text -> structured callouts. Pure functions, no PDF, no I/O.

Every parser returns None when the text is not that kind of callout. They
are deliberately strict: a callout we cannot parse is reported as unread,
which is better than a callout we parse into the wrong numbers.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- normalise

_CHAR_MAP = {
    "⌀": "Ø", "ø": "Ø", "∅": "Ø",
    "−": "-", "–": "-", "—": "-",
    "×": "x",
    " ": " ",
}


def normalise(text: str) -> str:
    out = "".join(_CHAR_MAP.get(c, c) for c in text)
    out = re.sub(r"(?<=\d),(?=\d)", ".", out)          # 12,5 -> 12.5 (European decimals)
    out = re.sub(r"\+/-", "±", out)
    return re.sub(r"\s+", " ", out).strip()


NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"

# ---------------------------------------------------------------- dimensions

_FIT = r"[A-Za-z]{1,2}\d{1,2}"
_DIM_RE = re.compile(
    rf"""^
    (?:(?P<count>\d+)\s*[xX]\s*)?                     # 4X
    (?P<ref_open>\()?
    (?P<prefix>SØ|SR|Ø|R|□)?\s*
    (?P<nom>{NUM})(?![\d.])
    (?P<deg>°)?
    (?:\s*(?P<tol>
        ±\s*(?P<sym>{NUM})°?
      | (?P<a>[+-]\s*{NUM}|(?<=\s)0)\s*/?\s*(?P<b>[+-]\s*{NUM}|0(?![\d.]))
      | /\s*(?P<lim>{NUM})
      | (?P<fit>{_FIT}(?:\s*/\s*{_FIT})?)(?:\s*\(.*\))?
      | (?P<onesided>MAX|MIN)
    ))?
    (?P<ref_close>\))?
    (?:\s*(?P<suffix>TYP|REF|THRU|BSC|BASIC))?
    $""",
    re.VERBOSE,
)


def _f(s: str | None) -> float | None:
    return float(s) if s not in (None, "") else None


def parse_dimension(text: str) -> dict[str, Any] | None:
    t = normalise(text)
    m = _DIM_RE.match(t)
    if not m:
        return None
    g = m.groupdict()
    nominal = float(g["nom"])
    d: dict[str, Any] = {
        "raw_nominal": g["nom"],
        "nominal": nominal,
        "prefix": g["prefix"] or "",
        "count": int(g["count"]) if g["count"] else 1,
        "angle": bool(g["deg"]),
        "tol_type": "none",
        "upper": None,
        "lower": None,
        "fit": None,
        "reference": bool(g["ref_open"] and g["ref_close"]) or g["suffix"] == "REF",
        "basic": g["suffix"] in ("BSC", "BASIC"),
        "suffix": g["suffix"] or "",
    }
    if g["ref_open"] and not g["ref_close"] or g["ref_close"] and not g["ref_open"]:
        return None
    if g["sym"] is not None:
        v = float(g["sym"])
        d.update(tol_type="symmetric", upper=v, lower=-v)
    elif g["a"] is not None:
        if not (g["a"][0] in "+-" or g["b"][0] in "+-"):
            return None
        # Written top line first: the first value is meant to be the upper deviation.
        # A drawing that writes them the other way round is a finding, not something to fix up.
        d.update(tol_type="bilateral", upper=float(g["a"].replace(" ", "")),
                 lower=float(g["b"].replace(" ", "")))
    elif g["lim"] is not None:
        other = float(g["lim"])
        hi, lo = max(nominal, other), min(nominal, other)
        # Limit dimensioning writes two sizes close together; "10/2" is not a limit.
        if hi == 0 or (hi - lo) / hi > 0.2:
            return None
        d.update(tol_type="limits", upper=round(hi - nominal, 6), lower=round(lo - nominal, 6),
                 limit_order="high_first" if nominal >= other else "low_first")
    elif g["fit"]:
        d.update(tol_type="fit", fit=g["fit"].replace(" ", ""))
    elif g["onesided"]:
        d.update(tol_type=g["onesided"].lower())
    return d


#: ISO 286 letters. Holes are capitals, shafts lower case.
_HOLE_LETTERS = {"A", "B", "C", "CD", "D", "E", "EF", "F", "FG", "G", "H", "JS", "J", "K",
                 "M", "N", "P", "R", "S", "T", "U", "V", "X", "Y", "Z", "ZA", "ZB", "ZC"}
_FIT_PART = re.compile(r"^([A-Za-z]{1,2})(\d{1,2})$")


def check_fit(fit: str) -> list[str]:
    """Problems with an ISO 286 fit designation like H7, g6 or H7/g6."""
    problems: list[str] = []
    parts = fit.split("/")
    for i, p in enumerate(parts):
        m = _FIT_PART.match(p)
        if not m:
            problems.append(f"'{p}' is not a tolerance class")
            continue
        letter, grade = m.group(1), int(m.group(2))
        if letter.upper() not in _HOLE_LETTERS:
            problems.append(f"'{letter}' is not an ISO 286 deviation letter")
        if not 1 <= grade <= 18:
            problems.append(f"IT grade {grade} is outside IT1-IT18")
        if len(parts) == 2 and letter[0].isupper() != (i == 0):
            problems.append(f"in a fit the hole class comes first in capitals and the "
                            f"shaft class second in lower case; got '{fit}'")
            break
    return problems


# ---------------------------------------------------------------- threads

_METRIC_THREAD = re.compile(
    rf"(?:(?P<count>\d+)\s*[xX]\s*)?\bM(?P<size>{NUM})(?:\s*[xX]\s*(?P<pitch>{NUM}))?"
    r"(?:\s*-\s*(?P<cls>\d[a-hA-H](?:\d[a-hA-H])?))?(?P<rest>.*)$"
)
_UNIFIED_THREAD = re.compile(
    r"(?:(?P<count>\d+)\s*[xX]\s*)?(?P<size>\d+/\d+|#\d+|\d*\.\d+|\d+)\s*-\s*(?P<tpi>\d+)\s*"
    r"(?P<series>UNC|UNF|UNEF|UNS|UN)(?:\s*-?\s*(?P<cls>[123][AB]))?(?P<rest>.*)$"
)
_PIPE_THREAD = re.compile(
    r"(?:\b(?P<pre>G|Rp|Rc|R)\s*(?P<size1>\d+(?:\s\d)?(?:/\d+)?)\b"
    r"|(?P<size2>\d+(?:/\d+)?)\s*-\s*(?P<tpi>\d+)\s*(?P<post>NPTF|NPT|BSPT|BSPP))(?P<rest>.*)$"
)


def parse_thread(text: str) -> dict[str, Any] | None:
    t = normalise(text)
    m = _METRIC_THREAD.search(t)
    if m and (m.start() == 0 or t[m.start() - 1] in " (" or m.group("count")):
        rest = m.group("rest")
        return {
            "system": "metric", "size": float(m.group("size")),
            "pitch": _f(m.group("pitch")), "class": m.group("cls"),
            "count": int(m.group("count")) if m.group("count") else 1,
            "depth": _depth(rest), "thru": "THRU" in rest.upper(),
        }
    m = _UNIFIED_THREAD.search(t)
    if m:
        rest = m.group("rest")
        return {
            "system": "unified", "size": m.group("size"), "tpi": int(m.group("tpi")),
            "series": m.group("series"), "class": m.group("cls"),
            "count": int(m.group("count")) if m.group("count") else 1,
            "depth": _depth(rest), "thru": "THRU" in rest.upper(),
        }
    m = _PIPE_THREAD.search(t)
    if m and (m.group("pre") or m.group("post")):
        return {
            "system": "pipe", "size": m.group("size1") or m.group("size2"),
            "series": m.group("pre") or m.group("post"), "class": None,
            "count": 1, "depth": _depth(m.group("rest")), "thru": "THRU" in m.group("rest").upper(),
        }
    return None


def _depth(rest: str) -> float | None:
    m = re.search(rf"(?:↧|DEEP|DP|DEPTH)\s*({NUM})|({NUM})\s*(?:DEEP|DP)", rest.upper())
    if not m:
        return None
    return float(m.group(1) or m.group(2))


# ---------------------------------------------------------------- surface finish

_ROUGH = re.compile(rf"\b(?P<param>Ra|Rz|Rmax|RMS|Rq)\s*=?\s*(?P<value>{NUM})\b")
_N_GRADE = re.compile(r"\bN(?P<grade>[1-9]|1[0-2])\b")
#: ISO 1302 Table: N-grade -> Ra in micrometres.
N_GRADE_RA = {1: 0.025, 2: 0.05, 3: 0.1, 4: 0.2, 5: 0.4, 6: 0.8, 7: 1.6, 8: 3.2,
              9: 6.3, 10: 12.5, 11: 25.0, 12: 50.0}
RA_PREFERRED = sorted(N_GRADE_RA.values())


def parse_surface(text: str, finish_context: bool = False) -> dict[str, Any] | None:
    t = normalise(text)
    m = _ROUGH.search(t)
    if m:
        return {"param": m.group("param"), "value": float(m.group("value"))}
    if finish_context:
        m = _N_GRADE.search(t)
        if m:
            g = int(m.group("grade"))
            return {"param": "N", "grade": g, "value": N_GRADE_RA[g]}
    return None


# ---------------------------------------------------------------- GD&T

#: characteristic -> (unicode symbols, category)
GDT_CHARACTERISTICS: dict[str, tuple[str, str]] = {
    "straightness": ("⏤", "form"),
    "flatness": ("▱⏥", "form"),
    "circularity": ("○", "form"),
    "cylindricity": ("⌭", "form"),
    "profile_line": ("⌒", "profile"),
    "profile_surface": ("⌓", "profile"),
    "parallelism": ("∥", "orientation"),
    "perpendicularity": ("⟂⊥", "orientation"),
    "angularity": ("∠", "orientation"),
    "position": ("⌖", "location"),
    "concentricity": ("◎", "location"),
    "symmetry": ("⌯", "location"),
    "circular_runout": ("↗", "runout"),
    "total_runout": ("⌰", "runout"),
}
_SYMBOL_TO_CHAR = {s: name for name, (syms, _) in GDT_CHARACTERISTICS.items() for s in syms}
GDT_SYMBOLS = "".join(_SYMBOL_TO_CHAR)

MODIFIERS = {"Ⓜ": "M", "Ⓛ": "L", "Ⓢ": "S", "Ⓕ": "F", "Ⓟ": "P", "Ⓣ": "T", "Ⓤ": "U"}

#: AutoCAD/Inventor GDT font (gdt.shx, AMGDT): a lower-case letter in that font
#: is drawn as a GD&T glyph. Applied only to words whose font name contains "gdt".
GDT_FONT_MAP = {
    "a": "∠", "b": "⟂", "c": "▱", "d": "⌓", "e": "○", "f": "∥", "g": "⌭",
    "h": "↗", "i": "⌯", "j": "⌖", "k": "⌒", "l": "Ⓛ", "m": "Ⓜ", "n": "Ø",
    "p": "Ⓟ", "r": "◎", "s": "Ⓢ", "t": "⌰", "u": "⏤",
    "v": "⌴", "w": "⌵", "x": "↧",          # counterbore, countersink, depth (seen in NIST ftc-07)
}


def translate_gdt_font(text: str) -> str:
    return "".join(GDT_FONT_MAP.get(c, c) for c in text)


def gdt_category(characteristic: str) -> str:
    return GDT_CHARACTERISTICS[characteristic][1]


def parse_fcf(text: str) -> dict[str, Any] | None:
    """A feature control frame written as one line of text, e.g.
    '⌖ Ø0.1 Ⓜ A B C', '⟂|0.05|A', '2X ⌖ Ø0.2 A-B'."""
    t = normalise(text).replace("|", " ")
    m = re.match(rf"^(?:(\d+)\s*[xX]\s*)?([{re.escape(GDT_SYMBOLS)}])\s*(.*)$", t)
    if not m:
        return None
    characteristic = _SYMBOL_TO_CHAR[m.group(2)]
    rest = m.group(3)
    # Common datum with per-letter modifiers, 'HⓂ-JⓂ': keep it one token 'H-J', remember the modifiers.
    compound_mods: dict[str, str] = {}

    def _compound(cm: re.Match) -> str:
        letters = []
        for part in cm.group(0).split("-"):
            letters.append(part[0])
            if len(part) > 1:
                compound_mods[part[0]] = MODIFIERS[part[1]]
        return "-".join(letters)

    rest = re.sub(r"(?<![A-Za-z])[A-Z][ⓂⓁⓈ]?(?:-[A-Z][ⓂⓁⓈ]?)+", _compound, rest)
    for sym, letter in MODIFIERS.items():
        rest = rest.replace(sym, f" ({letter}) ")
    # 'Ⓜ F A B' : a bare F or P straight after a material modifier is the free-state /
    # projected-zone modifier written without its circle, not datum F or P.
    rest = re.sub(r"(\([ML]\))\s+([FP])(?=\s+[A-Z]\b|\s*$)", r"\1 (\2)", rest)
    tokens = rest.split()
    zone_dia = False
    tol: float | None = None
    material = None
    other_mods: list[str] = []
    datums: list[str] = []
    datum_mods: dict[str, str] = {}
    i = 0
    if i < len(tokens) and tokens[i] in ("Ø", "SØ"):
        zone_dia = True
        i += 1
    if i < len(tokens):
        tok = tokens[i]
        if tok.startswith("Ø"):
            zone_dia, tok = True, tok[1:]
        if re.fullmatch(NUM, tok):
            tol = float(tok)
            i += 1
    max_tol: float | None = None
    while i < len(tokens):
        tok = tokens[i]
        if re.fullmatch(r"\([A-Z]\)", tok):
            mod = tok[1]
            if mod in ("M", "L", "S"):
                material = mod
            else:
                other_mods.append(mod)
            i += 1
        elif tok in ("ST", "(ST)", "⟨ST⟩"):                      # statistical tolerance
            other_mods.append("ST")
            i += 1
        elif i + 1 < len(tokens) and tokens[i + 1] == "MAX" and re.fullmatch(rf"Ø?{NUM}", tok):
            max_tol = float(tok.lstrip("Ø"))                     # 'Ø.045 MAX' caps the bonus
            i += 2
        else:
            break
    while i < len(tokens):
        tok = tokens[i]
        if re.fullmatch(r"[A-Z](?:-[A-Z])*", tok):
            datums.append(tok)
        elif re.fullmatch(r"\([A-Z]\)", tok) and datums:
            datum_mods[datums[-1]] = tok[1]
        else:
            return None   # something we do not understand: refuse rather than guess
        i += 1
    if tol is None:
        return None
    return {
        "characteristic": characteristic,
        "category": gdt_category(characteristic),
        "count": int(m.group(1)) if m.group(1) else 1,
        "diameter_zone": zone_dia,
        "tolerance": tol,
        "material": material,
        "modifiers": other_mods,
        "max_tolerance": max_tol,
        "datums": datums,
        "datum_modifiers": {**compound_mods, **datum_mods},
    }


_HEADLESS = re.compile(
    rf"""^(?:(?P<count>\d+)\s*[xX]\s+)?(?P<dia>Ø)?(?P<tol>{NUM})
    (?:\s*(?P<mat>[MLⓂⓁ])(?=\s+[A-Z]\b|\s*$))?
    (?:\s*[PⓅ]\s*(?P<proj>{NUM}))?
    (?P<datums>(?:\s+[A-Z](?:-[A-Z])?(?:\s*[ⓂⓁ])?)+)$""",
    re.VERBOSE,
)


def parse_headless_fcf(text: str) -> dict[str, Any] | None:
    """A frame whose characteristic symbol the PDF drew as geometry, so the
    text layer holds only '<tol> <datums>', e.g. 'Ø.015 A B C'. The datum
    references are real and checkable; the characteristic is unknown (None)."""
    t = normalise(text).replace("|", " ")
    m = _HEADLESS.match(t)
    if not m:
        return None
    raw = m.group("tol")
    tol = float(raw)
    # Geometric tolerances are small and written with a decimal point; '25 B' is a dimension next to a datum.
    if "." not in raw or tol > 2.0:
        return None
    datums, mods = [], {}
    for tok in m.group("datums").split():
        if tok in ("Ⓜ", "Ⓛ") and datums:
            mods[datums[-1]] = MODIFIERS[tok]
        else:
            datums.append(tok)
    mat = m.group("mat")
    return {
        "characteristic": None, "category": None, "headless": True,
        "count": int(m.group("count")) if m.group("count") else 1,
        "diameter_zone": bool(m.group("dia")), "tolerance": tol,
        "material": MODIFIERS.get(mat, mat) if mat else None,
        "modifiers": ["P"] if m.group("proj") else [],
        "datums": datums, "datum_modifiers": mods,
    }


def datum_letters(refs: list[str]) -> list[str]:
    """'A-B' is a common datum made of A and B."""
    out: list[str] = []
    for r in refs:
        out.extend(r.split("-"))
    return out


# ---------------------------------------------------------------- notes / statements

_ISO2768 = re.compile(
    r"(?:DIN\s*|IS\s*)?(?:ISO|IS)\s*2768(?:\s*-\s*[12])?\s*(?:[-:]\s*)?(?P<lin>[fmcvFMCV])?\s*-?\s*(?P<geo>[HKL])?\b"
)
_IS2102 = re.compile(r"\bIS\s*2102(?:\s*\(?\s*PART\s*[12]\s*\)?)?\s*[-:]?\s*(?P<cls>[fmcvFMCV]|FINE|MEDIUM|COARSE)?", re.I)
_UOS_TOL = re.compile(rf"(UNLESS\s+OTHERWISE\s+(?:SPECIFIED|STATED|NOTED)|U\.?O\.?S\.?|GENERAL\s+TOLERANCES?).*?±\s*{NUM}|X\.X+\s*±\s*{NUM}", re.I)


def parse_general_tolerance(text: str) -> dict[str, Any] | None:
    t = normalise(text)
    m = _ISO2768.search(t.upper()) if "2768" in t else None
    if m:
        return {"standard": "ISO 2768", "linear_class": (m.group("lin") or "").lower() or None,
                "geometric_class": (m.group("geo") or "").upper() or None}
    m = _IS2102.search(t) if "2102" in t else None
    if m:
        cls = (m.group("cls") or "").lower()
        cls = {"fine": "f", "medium": "m", "coarse": "c"}.get(cls, cls) or None
        return {"standard": "IS 2102", "linear_class": cls, "geometric_class": None}
    if "22081" in t and "ISO" in t.upper():
        return {"standard": "ISO 22081", "linear_class": None, "geometric_class": None}
    if _UOS_TOL.search(t):
        return {"standard": "block", "linear_class": None, "geometric_class": None}
    u = t.upper()
    # "<profile frame> APPLIES TO ALL UNTOLERANCED SURFACES" is a general tolerance too.
    if re.search(r"\b(ALL|OTHER)\s+UNTOLERANCED\b|\bAPPL\w*\s+TO\s+ALL\s+UNTOLERANCED", u):
        return {"standard": "untoleranced_note", "linear_class": None, "geometric_class": None}
    # Model-based definition: "the model represents basic dimensional data".
    if re.search(r"\bMODEL\b.*\bBASIC\b|\bBASIC\b.*\bDEFINED\s+BY\s+THE\s+MODEL", u):
        return {"standard": "model_basic", "linear_class": None, "geometric_class": None}
    return None


_STANDARDS = [
    ("ASME Y14.5", re.compile(r"\b(?:ASME|ANSI)\s*Y\s*14\.5(?:M)?(?:\s*-?\s*(\d{4}))?", re.I)),
    ("ISO 1101", re.compile(r"\bISO\s*1101", re.I)),
    ("ISO 8015", re.compile(r"\bISO\s*8015", re.I)),
    ("ISO 2768", re.compile(r"\bISO\s*2768", re.I)),
    ("ISO 1302", re.compile(r"\bISO\s*1302", re.I)),
    ("ISO 21920", re.compile(r"\bISO\s*21920", re.I)),
    ("ISO 286", re.compile(r"\bISO\s*286", re.I)),
    ("IS 919", re.compile(r"\bIS\s*919\b", re.I)),
    ("IS 2102", re.compile(r"\bIS\s*2102\b", re.I)),
    ("BS 8888", re.compile(r"\bBS\s*8888", re.I)),
    ("ISO 128", re.compile(r"\bISO\s*128\b", re.I)),
]


def find_standards(text: str) -> list[dict[str, Any]]:
    t = normalise(text)
    out = []
    for name, rx in _STANDARDS:
        m = rx.search(t)
        if m:
            year = m.group(1) if m.groups() and m.group(1) else None
            out.append({"standard": name, "year": year})
    return out


def parse_projection(text: str) -> str | None:
    t = normalise(text).upper()
    first = re.search(r"\b(FIRST|1ST)\s*ANGLE", t)
    third = re.search(r"\b(THIRD|3RD)\s*ANGLE", t)
    if first and third:
        return "both"
    if first:
        return "first"
    if third:
        return "third"
    return None


def parse_units(text: str) -> str | None:
    t = normalise(text).upper()
    if re.search(r"\b(MILLIMET(?:RE|ER)S?|IN\s+MM|UNITS?\s*[:=]?\s*MM|\(MM\)|DIMENSIONS?\s+(?:ARE\s+)?IN\s+MM)\b", t):
        return "mm"
    if re.search(r"\b(INCH(?:ES)?|IN\s+INCHES|UNITS?\s*[:=]?\s*(?:IN|INCH))\b", t):
        return "inch"
    if re.fullmatch(r"MM", t):
        return "mm"
    return None


# ---------------------------------------------------------------- title block labels

TITLE_LABELS: dict[str, tuple[str, ...]] = {
    "drawing_number": ("DWG NO", "DWG. NO", "DRAWING NO", "DRAWING NUMBER", "DRG NO", "DRG. NO", "DOC NO", "DOCUMENT NO"),
    "part_number": ("PART NO", "PART NUMBER", "P/N", "ITEM NO", "PART NO."),
    "title": ("TITLE", "DESCRIPTION", "PART NAME", "DRAWING TITLE"),
    "revision": ("REV", "REVISION", "REV."),
    "material": ("MATERIAL", "MATL", "MAT'L", "MATERIAL SPEC"),
    "scale": ("SCALE",),
    "units": ("UNITS", "UNIT"),
    "sheet": ("SHEET", "SHT"),
    "drawn_by": ("DRAWN", "DRAWN BY", "DRN", "DRN BY", "DESIGNED", "DESIGNED BY"),
    "checked_by": ("CHECKED", "CHECKED BY", "CHKD", "CHK"),
    "approved_by": ("APPROVED", "APPROVED BY", "APPD", "APPR", "APPROVAL"),
    "date": ("DATE",),
    "finish": ("FINISH", "SURFACE TREATMENT", "TREATMENT", "COATING"),
    "mass": ("WEIGHT", "MASS"),
    "projection": ("PROJECTION",),
    "tolerance": ("TOLERANCE", "TOLERANCES", "GENERAL TOLERANCE"),
    "size": ("SIZE",),
}
_LABEL_INDEX = sorted(
    ((lab, name) for name, labs in TITLE_LABELS.items() for lab in labs),
    key=lambda x: -len(x[0]),
)


def match_label(text: str) -> tuple[str, str] | None:
    """If text starts with a title-block label, return (field, remainder)."""
    t = normalise(text).upper()
    for lab, name in _LABEL_INDEX:
        if t == lab or t.startswith(lab + " ") or t.startswith(lab + ":") or t.startswith(lab + "."):
            rest = normalise(text)[len(lab):].lstrip(" :.-").strip()
            return name, rest
    return None
