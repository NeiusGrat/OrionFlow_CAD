"""Engineering standards knowledge — deterministic tables + retrieval.

The LLM must never recall standard dimensions from memory: bearing envelopes,
fastener holes, and motor mount patterns come from these tables (Agent 8 of
the v2 architecture, "knowledge retrieval replaces hallucination").

Two consumers:
  * the spec stage (``detect``) auto-attaches standards named in the request
    to ``EngineeringSpec.standards`` — a sanctioned channel for numbers the
    user never typed, deliberately separate from the grounding-guarded
    ``dimensions``;
  * the ``lookup_standard`` tool (``search``) lets the model retrieve
    mid-turn, e.g. "tapered roller bore 20".

Pure stdlib, deterministic. Values are nominal catalogue dimensions in mm.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# bearings: designation -> (type, bore d, outer D, width B/T)
# --------------------------------------------------------------------------- #

_DG = "deep groove ball"
_TR = "tapered roller"

BEARINGS: dict[str, dict] = {des: {"type": t, "bore": d, "od": D, "width": B}
                             for des, t, d, D, B in [
    ("625", _DG, 5, 16, 5),
    ("626", _DG, 6, 19, 6),
    ("608", _DG, 8, 22, 7),
    ("6000", _DG, 10, 26, 8), ("6001", _DG, 12, 28, 8),
    ("6002", _DG, 15, 32, 9), ("6003", _DG, 17, 35, 10),
    ("6004", _DG, 20, 42, 12), ("6005", _DG, 25, 47, 12),
    ("6006", _DG, 30, 55, 13), ("6007", _DG, 35, 62, 14),
    ("6008", _DG, 40, 68, 15), ("6009", _DG, 45, 75, 16),
    ("6010", _DG, 50, 80, 16),
    ("6200", _DG, 10, 30, 9), ("6201", _DG, 12, 32, 10),
    ("6202", _DG, 15, 35, 11), ("6203", _DG, 17, 40, 12),
    ("6204", _DG, 20, 47, 14), ("6205", _DG, 25, 52, 15),
    ("6206", _DG, 30, 62, 16), ("6207", _DG, 35, 72, 17),
    ("6208", _DG, 40, 80, 18), ("6209", _DG, 45, 85, 19),
    ("6210", _DG, 50, 90, 20),
    ("6300", _DG, 10, 35, 11), ("6301", _DG, 12, 37, 12),
    ("6302", _DG, 15, 42, 13), ("6303", _DG, 17, 47, 14),
    ("6304", _DG, 20, 52, 15), ("6305", _DG, 25, 62, 17),
    ("6306", _DG, 30, 72, 19),
    ("30203", _TR, 17, 40, 13.25), ("30204", _TR, 20, 47, 15.25),
    ("30205", _TR, 25, 52, 16.25), ("30206", _TR, 30, 62, 17.25),
    ("30207", _TR, 35, 72, 18.25), ("30208", _TR, 40, 80, 19.75),
    ("30209", _TR, 45, 85, 20.75), ("30210", _TR, 50, 90, 21.75),
    ("32004", _TR, 20, 42, 15), ("32005", _TR, 25, 47, 15),
    ("32006", _TR, 30, 55, 17), ("32007", _TR, 35, 62, 18),
    ("32008", _TR, 40, 68, 19), ("32009", _TR, 45, 75, 20),
    ("32010", _TR, 50, 80, 20),
]}

# --------------------------------------------------------------------------- #
# ISO metric fasteners (coarse thread): size -> dims
#   clearance per ISO 273 (normal / close), tap drill for coarse pitch,
#   socket head cap screw (ISO 4762) head, counterbore, hex nut A/F (ISO 4032)
# --------------------------------------------------------------------------- #

FASTENERS: dict[str, dict] = {size: {
    "pitch": p, "clearance_normal": cn, "clearance_close": cc, "tap_drill": td,
    "shcs_head_d": hd, "shcs_head_h": hh, "cbore_d": cb, "nut_af": af,
} for size, p, cn, cc, td, hd, hh, cb, af in [
    ("M2", 0.4, 2.4, 2.2, 1.6, 3.8, 2.0, 4.4, 4.0),
    ("M2.5", 0.45, 2.9, 2.7, 2.05, 4.5, 2.5, 5.4, 5.0),
    ("M3", 0.5, 3.4, 3.2, 2.5, 5.5, 3.0, 6.5, 5.5),
    ("M4", 0.7, 4.5, 4.3, 3.3, 7.0, 4.0, 8.0, 7.0),
    ("M5", 0.8, 5.5, 5.3, 4.2, 8.5, 5.0, 10.0, 8.0),
    ("M6", 1.0, 6.6, 6.4, 5.0, 10.0, 6.0, 11.0, 10.0),
    ("M8", 1.25, 9.0, 8.4, 6.8, 13.0, 8.0, 15.0, 13.0),
    ("M10", 1.5, 11.0, 10.5, 8.5, 16.0, 10.0, 18.0, 16.0),
    ("M12", 1.75, 13.5, 13.0, 10.2, 18.0, 12.0, 20.0, 18.0),
    ("M16", 2.0, 17.5, 17.0, 14.0, 24.0, 16.0, 26.0, 24.0),
    ("M20", 2.5, 22.0, 21.0, 17.5, 30.0, 20.0, 33.0, 30.0),
]}

# --------------------------------------------------------------------------- #
# NEMA stepper motor mounts: size -> dims (square bolt pattern)
# --------------------------------------------------------------------------- #

NEMA: dict[int, dict] = {n: {
    "faceplate": fp, "bolt_spacing": bs, "bolt": bolt,
    "pilot_d": pd, "shaft_d": sd,
} for n, fp, bs, bolt, pd, sd in [
    (8, 20.3, 15.4, "M2", 15.0, 4.0),
    (11, 28.2, 23.0, "M2.5", 22.0, 5.0),
    (14, 35.2, 26.0, "M3", 22.0, 5.0),
    (17, 42.3, 31.0, "M3", 22.0, 5.0),
    (23, 56.4, 47.14, "5.1 mm holes (M5 clearance)", 38.1, 6.35),
    (34, 86.0, 69.6, "6.5 mm holes (M6 clearance)", 73.03, 14.0),
]}


# --------------------------------------------------------------------------- #
# entry construction / rendering
# --------------------------------------------------------------------------- #


def _bearing_entry(des: str, candidate: bool = False) -> dict:
    row = BEARINGS[des]
    text = ("bearing %s (%s): bore %g mm x OD %g mm x width %g mm "
            "(typical fits: housing H7, shaft k6)"
            % (des, row["type"], row["bore"], row["od"], row["width"]))
    return {"kind": "bearing", "designation": des, "candidate": candidate,
            "text": text, **row}


def _fastener_entry(size: str) -> dict:
    row = FASTENERS[size]
    text = ("%s (ISO coarse, pitch %g): clearance hole %g mm (close fit %g), "
            "tap drill %g mm, socket head ø%g x %g mm, counterbore ø%g mm, "
            "hex nut %g mm A/F"
            % (size, row["pitch"], row["clearance_normal"],
               row["clearance_close"], row["tap_drill"], row["shcs_head_d"],
               row["shcs_head_h"], row["cbore_d"], row["nut_af"]))
    return {"kind": "fastener", "designation": size, "candidate": False,
            "text": text, **row}


def _nema_entry(n: int) -> dict:
    row = NEMA[n]
    text = ("NEMA %d stepper mount: %g mm square bolt pattern (%s), pilot "
            "boss ø%g mm, shaft ø%g mm, faceplate %g mm square"
            % (n, row["bolt_spacing"], row["bolt"], row["pilot_d"],
               row["shaft_d"], row["faceplate"]))
    return {"kind": "nema", "designation": f"NEMA {n}", "candidate": False,
            "text": text, **row}


def render(entries: list[dict]) -> str:
    return "\n".join("- " + e["text"] for e in entries)


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #

_BEARING_WORDS = ("bearing", "bearings")
_BORE_WORDS = r"(?:bore|axle|shaft|spindle|arbor)"


def _find_bore(text: str) -> float | None:
    """A number tied to a bore-ish word: '20 mm wheel axle' / 'bore of 20'."""
    m = (re.search(r"(\d+(?:\.\d+)?)\s*(?:mm\s*)?[\w\s-]{0,12}?\b" + _BORE_WORDS, text)
         or re.search(_BORE_WORDS + r"\D{0,12}?(\d+(?:\.\d+)?)", text))
    return float(m.group(1)) if m else None


def _bearing_type_filter(text: str) -> str | None:
    if "taper" in text:
        return _TR
    if "deep groove" in text or "ball" in text:
        return _DG
    return None


def detect(message: str, limit: int = 6) -> list[dict]:
    """High-confidence standards named in a request, for spec auto-attach.

    Exact bearing designations, NEMA sizes, and M-thread sizes attach
    directly. A bearing *type* plus a bore dimension (but no designation)
    attaches ranked candidates, flagged ``candidate: true``.
    """
    text = message.lower()
    found: list[dict] = []
    seen: set = set()

    for m in re.finditer(r"\b(\d{3,5})\b", text):
        des = m.group(1)
        if des in BEARINGS and des not in seen:
            found.append(_bearing_entry(des))
            seen.add(des)

    for m in re.finditer(r"\bnema\s*-?\s*(\d{1,2})\b", text):
        n = int(m.group(1))
        if n in NEMA and ("nema", n) not in seen:
            found.append(_nema_entry(n))
            seen.add(("nema", n))

    for m in re.finditer(r"\bm(\d+(?:\.\d+)?)\b", text):
        size = "M" + m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) \
            else "M" + m.group(1)
        if size in FASTENERS and size not in seen:
            found.append(_fastener_entry(size))
            seen.add(size)

    # No designation, but "bearing" + a bore -> ranked candidates.
    if not any(e["kind"] == "bearing" for e in found) \
            and any(w in text for w in _BEARING_WORDS):
        bore = _find_bore(text)
        if bore is not None:
            btype = _bearing_type_filter(text)
            cands = [des for des, row in BEARINGS.items()
                     if row["bore"] == bore
                     and (btype is None or row["type"] == btype)]
            for des in cands[:3]:
                found.append(_bearing_entry(des, candidate=True))

    return found[:limit]


def search(query: str, limit: int = 5) -> list[dict]:
    """Free-text lookup for the ``lookup_standard`` tool."""
    hits = detect(query, limit=limit)
    if hits:
        return hits
    # Bearing-type browse without a bore ("tapered roller bearings").
    text = query.lower()
    btype = _bearing_type_filter(text)
    if btype and any(w in text for w in _BEARING_WORDS):
        bore = _find_bore(text)
        cands = [des for des, row in BEARINGS.items()
                 if row["type"] == btype
                 and (bore is None or row["bore"] == bore)]
        return [_bearing_entry(des, candidate=True) for des in cands[:limit]]
    return []
