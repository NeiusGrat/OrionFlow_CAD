"""Rendered page -> annotations, through a vision model.

The model only transcribes: what each callout says and where it is. It does
not judge anything. Its text goes through the same deterministic parsers as
the PDF text layer, and the same rules run on the result.

Where a page also has a text layer, every vision annotation is checked against
it:
  confirmed  the text layer has the same callout at the same place
  conflict   the text layer says something else; the text layer wins and the
             disagreement is recorded (it measures how well the model reads)
  vision     the model saw something the text layer does not have (a symbol
             drawn as geometry, an outlined or scanned page). Findings that
             rest on these are marked for the reviewer to verify.

Provider: Gemini over REST (GEMINI_API_KEY). Responses are cached on disk by
image hash, so re-running a drawing costs nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import parse
from .extract_vector import statement_data
from .ingest import render_page
from .model import Annotation, BBox, Drawing, Page

PROMPT_VERSION = "v2"
DEFAULT_MODEL = os.environ.get("DRAWCHECK_VISION_MODEL", "gemini-flash-latest")
#: Tried in order when the model above is overloaded (HTTP 429/503).
FALLBACK_MODELS = [m for m in os.environ.get(
    "DRAWCHECK_VISION_FALLBACKS", "gemini-3.5-flash,gemini-2.5-flash").split(",") if m]
DPI = int(os.environ.get("DRAWCHECK_VISION_DPI", "200"))
MAX_SIDE = 3072          # pixels; larger renders are scaled down to this
CACHE_DIR = Path(os.environ.get("DRAWCHECK_CACHE", Path.home() / ".cache" / "drawcheck"))


class VisionUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------ prompt and schema

CHARACTERISTICS = ["straightness", "flatness", "circularity", "cylindricity", "profile_line",
                   "profile_surface", "parallelism", "perpendicularity", "angularity", "position",
                   "concentricity", "symmetry", "circular_runout", "total_runout", "unknown"]
TITLE_FIELDS = ["drawing_number", "part_number", "title", "revision", "material", "scale", "units",
                "sheet", "drawn_by", "checked_by", "approved_by", "date", "finish", "mass",
                "projection", "tolerance", "size", "other"]

PROMPT = """You are reading a mechanical engineering drawing for a quality check.
Transcribe every annotation on this page. Do not judge, correct or complete anything:
report exactly what is printed, character for character, including mistakes.

For each annotation give:
- kind: one of
    dimension       a size or angle callout (with its own tolerance if it has one)
    gdt_frame       a feature control frame (the boxed geometric tolerance)
    datum_feature   a datum feature symbol: a boxed single letter attached to a feature by a triangle
    thread          a thread callout (M8x1.25-6H, 1/4-20 UNC-2B, G1/4 ...)
    surface_finish  a surface texture symbol or Ra/Rz value
    note            one numbered note, or one general statement line (tolerances, units, standards)
    title_field     one filled-in field of the title block
    projection      a first-angle or third-angle projection statement or symbol
- text: the callout exactly as printed. Rules:
    * keep decimals exactly as printed (".250" stays ".250", "0,5" stays "0,5")
    * keep count prefixes ("4X Ø6.6 THRU")
    * a stacked tolerance is written top line first: "Ø30 +0.021/0", "10 +0.1/-0.05"
    * use these symbols: Ø ± ° and for GD&T ⏤ ▱ ○ ⌭ ⌒ ⌓ ∥ ⟂ ∠ ⌖ ◎ ⌯ ↗ ⌰, modifiers Ⓜ Ⓛ Ⓟ Ⓕ Ⓢ
    * a feature control frame as its cells separated by spaces: "⌖ Ø0.2 Ⓜ A B C"
    * a note with its number: "2. GENERAL TOLERANCES ISO 2768-mK"
    * a title field as its value only (the label goes in `field`)
- box_2d: [ymin, xmin, ymax, xmax] of the annotation, normalised to 0-1000.
- For dimension also: basic (true when the value is enclosed in a rectangle).
- For gdt_frame also: characteristic, tolerance (number), diameter_zone, material_modifier, datums
  (letters in order, "A-B" for a common datum).
- For title_field also: field.
- For projection also: projection ("first" or "third"). The ISO projection symbol is a truncated cone
  beside two concentric circles; circles on the RIGHT of the cone = first angle, on the LEFT = third angle.

Skip: border zone letters and numbers, item balloons, view labels, leader lines, the drawing geometry itself.
If a callout is present but you cannot read it, include it with text "?". Never guess a number."""

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "annotations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "kind": {"type": "STRING", "enum": ["dimension", "gdt_frame", "datum_feature", "thread",
                                                        "surface_finish", "note", "title_field", "projection"]},
                    "text": {"type": "STRING"},
                    "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "characteristic": {"type": "STRING", "enum": CHARACTERISTICS},
                    "tolerance": {"type": "NUMBER"},
                    "basic": {"type": "BOOLEAN"},
                    "diameter_zone": {"type": "BOOLEAN"},
                    "material_modifier": {"type": "STRING", "enum": ["none", "MMC", "LMC"]},
                    "datums": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "field": {"type": "STRING", "enum": TITLE_FIELDS},
                    "projection": {"type": "STRING", "enum": ["first", "third"]},
                },
                "required": ["kind", "text", "box_2d"],
            },
        },
    },
    "required": ["annotations"],
}


# ------------------------------------------------------------------ provider

def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    for env in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"^\s*(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(2).strip("'\"")
    raise VisionUnavailable("no GEMINI_API_KEY in the environment or .env")


class _Overloaded(RuntimeError):
    pass


def call_gemini(png: bytes, model: str = DEFAULT_MODEL, timeout: float = 180.0) -> tuple[dict, dict]:
    """(parsed JSON, usage), trying fallback models when one is overloaded."""
    chain = [model] + [f for f in FALLBACK_MODELS if f != model]
    # Any model's earlier answer for this exact page beats waiting on an overloaded one.
    for m in chain:
        cache = _cache_path(png, m)
        if cache.exists():
            hit = json.loads(cache.read_text(encoding="utf-8"))
            return hit["result"], {**hit["usage"], "cached": True}
    errors = []
    for m in chain:
        try:
            return _call_one(png, m, timeout)
        except _Overloaded as e:
            errors.append(f"{m}: {e}")
    raise VisionUnavailable("all vision models overloaded: " + " | ".join(errors))


def _cache_path(png: bytes, model: str) -> Path:
    digest = hashlib.sha256(png + PROMPT.encode() + model.encode() + PROMPT_VERSION.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _call_one(png: bytes, model: str, timeout: float) -> tuple[dict, dict]:
    """One model. Cached by image + prompt + model."""
    import httpx

    cache = _cache_path(png, model)
    if cache.exists():
        hit = json.loads(cache.read_text(encoding="utf-8"))
        return hit["result"], {**hit["usage"], "cached": True}

    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}},
            {"text": PROMPT},
        ]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            # Drawings are dense: small text is lost at the default image resolution.
            "mediaResolution": "MEDIA_RESOLUTION_HIGH",
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last: Exception | None = None
    for attempt in range(2):
        t0 = time.time()
        try:
            r = httpx.post(url, headers={"x-goog-api-key": _api_key()}, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            last = e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise VisionUnavailable(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        reason = cand.get("finishReason", "")
        if reason in ("RECITATION", "SAFETY", "PROHIBITED_CONTENT", "OTHER") and not cand.get("content"):
            # Refused, e.g. RECITATION on drawings published online. Another model may answer.
            raise _Overloaded(f"{model} refused: {reason}")
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise VisionUnavailable(f"unexpected Gemini response: {str(data)[:300]}") from e
        meta = data.get("usageMetadata", {})
        usage = {"model": model, "seconds": round(time.time() - t0, 1), "input_tokens": meta.get("promptTokenCount", 0),
                 "output_tokens": meta.get("candidatesTokenCount", 0) + meta.get("thoughtsTokenCount", 0)}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"result": result, "usage": usage}), encoding="utf-8")
        return result, {**usage, "cached": False}
    raise _Overloaded(str(last)[:160])


# ------------------------------------------------------------------ conversion

def _bbox(box: list, page: Page) -> BBox | None:
    if not isinstance(box, list) or len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in box)
    if xmax <= xmin or ymax <= ymin:
        return None
    return (xmin / 1000 * page.width, ymin / 1000 * page.height,
            xmax / 1000 * page.width, ymax / 1000 * page.height)


_CHAR_SYMBOL = {name: syms[0] for name, (syms, _) in parse.GDT_CHARACTERISTICS.items()}


def _frame(item: dict) -> dict | None:
    """The printed text first, parsed like any other frame; the model's structured
    fields only when the text does not parse. (Structured `datums` came back empty
    on real drawings while the text plainly listed them.)"""
    text = item.get("text", "")
    fcf = parse.parse_fcf(text)
    if fcf:
        return fcf
    char = item.get("characteristic")
    tol = item.get("tolerance")
    if char in _CHAR_SYMBOL and isinstance(tol, (int, float)):
        cells = [_CHAR_SYMBOL[char], ("Ø" if item.get("diameter_zone") else "") + f"{tol:g}"]
        mod = {"MMC": "Ⓜ", "LMC": "Ⓛ"}.get(item.get("material_modifier") or "")
        if mod:
            cells.append(mod)
        cells += [d.strip().upper() for d in item.get("datums") or [] if d.strip()]
        fcf = parse.parse_fcf(" ".join(cells))
        # The printed frame did not parse; if it shows datum letters the structured
        # fields left out, we do not know the datums. Report unreadable, never "none".
        printed_letters = re.findall(r"(?<![A-Za-z])[A-Z](?![A-Za-z])", text.split(None, 1)[-1] if text else "")
        if fcf and not fcf["datums"] and printed_letters:
            return None
        if fcf:
            return fcf
    fcf = parse.parse_headless_fcf(text)
    if fcf:
        return fcf
    return None


def to_annotation(item: dict, page: Page) -> Annotation | None:
    kind, text = item.get("kind"), (item.get("text") or "").strip()
    bbox = _bbox(item.get("box_2d"), page)
    if not kind or bbox is None or not text:
        return None
    if text == "?":
        return Annotation(kind, text, page.index, bbox, "vision", {"illegible": True})
    if kind == "dimension":
        d = parse.parse_dimension(text)
        if d and item.get("basic"):
            d["basic"] = True
        return Annotation(kind, text, page.index, bbox, "vision", d or {"unparsed": True})
    if kind == "gdt_frame":
        f = _frame(item)
        return Annotation(kind, text, page.index, bbox, "vision", f or {"unparsed": True})
    if kind == "datum_feature":
        letter = re.sub(r"[^A-Z]", "", text.upper())
        return Annotation(kind, letter, page.index, bbox, "vision", {"letter": letter}) if len(letter) == 1 else None
    if kind == "thread":
        t = parse.parse_thread(text)
        return Annotation(kind, text, page.index, bbox, "vision", t) if t else None
    if kind == "surface_finish":
        s = parse.parse_surface(text, finish_context=True)
        return Annotation(kind, text, page.index, bbox, "vision", s) if s else None
    if kind == "note":
        return Annotation(kind, text, page.index, bbox, "vision", statement_data(text))
    if kind == "title_field":
        field = item.get("field") or "other"
        return Annotation(kind, text, page.index, bbox, "vision", {"field": field})
    if kind == "projection":
        method = item.get("projection") or parse.parse_projection(text)
        return Annotation(kind, text, page.index, bbox, "vision", {"method": method}) if method else None
    return None


# ------------------------------------------------------------------ cross-check

def _near(a: BBox, b: BBox, pad: float = 8.0) -> bool:
    return a[0] - pad < b[2] and b[0] - pad < a[2] and a[1] - pad < b[3] and b[1] - pad < a[3]


def _dist(a: BBox, b: BBox) -> float:
    return abs((a[0] + a[2]) - (b[0] + b[2])) + abs((a[1] + a[3]) - (b[1] + b[3]))


def _same_values(v: Annotation, a: Annotation) -> bool | None:
    """True/False when both sides carry comparable numbers; None when they do not."""
    if v.kind == "dimension":
        keys = ("nominal", "upper", "lower", "fit", "count")
    elif v.kind == "gdt_frame":
        # On a frame whose symbol is geometry, a circled modifier usually is too: compare what the text holds.
        keys = ("tolerance", "datums") if v.data.get("headless") else ("tolerance", "datums", "material")
    elif v.kind == "datum_feature":
        keys = ("letter",)
    elif v.kind == "thread":
        keys = ("size", "pitch", "class")
    else:
        return None
    if v.data.get("unparsed") or a.data.get("unparsed"):
        return None
    return all(v.data.get(k) == a.data.get(k) for k in keys)


def merge(drawing: Drawing, page: Page, found: list[Annotation]) -> dict[str, int]:
    stats = {"confirmed": 0, "conflict": 0, "vision_only": 0, "duplicate": 0}
    vec = [v for v in drawing.annotations if v.page == page.index and v.source != "vision"]
    for a in found:
        cands = [v for v in vec if v.kind == a.kind and _near(v.bbox, a.bbox)]
        if not cands:
            drawing.annotations.append(a)
            stats["vision_only"] += 1
            continue
        same = [(v, _same_values(v, a)) for v in cands]
        hit = next((v for v, s in same if s), None)
        if hit is not None:
            # A frame whose symbol the PDF drew as geometry: the model supplies the characteristic.
            # The text layer confirmed the tolerance and datums, NOT the symbol (Gemini reads
            # profile ⌓ as flatness ▱), so anything resting on the symbol stays "vision".
            if (hit.kind == "gdt_frame" and hit.data.get("headless") and a.data.get("characteristic")
                    and a.data.get("category") == "form" and hit.data.get("datums")):
                # Form tolerances never take datums; the text layer proves this frame has them,
                # so the symbol the model saw (typically profile ⌓ read as flatness ▱) is wrong.
                drawing.warnings.append(f"page {page.index + 1}: vision symbol in '{a.text}' contradicts the "
                                        f"datums in '{hit.text}'; symbol left unread")
                hit.source = "confirmed"
            elif hit.kind == "gdt_frame" and hit.data.get("headless") and a.data.get("characteristic"):
                hit.data.update(characteristic=a.data["characteristic"], category=a.data["category"],
                                headless=False, characteristic_source="vision")
                hit.data["text_layer"] = hit.text
                hit.text = a.text
                hit.source = "vision"
            else:
                hit.source = "confirmed"
            stats["confirmed"] += 1
        elif any(s is False for _, s in same):
            # Frames sit a few points apart: compare against the nearest one, not any neighbour.
            v = min((v for v, s in same if s is False), key=lambda v: _dist(v.bbox, a.bbox))
            drawing.warnings.append(f"page {page.index + 1}: vision read '{a.text}' where the text layer "
                                    f"says '{v.data.get('text_layer', v.text)}'; text layer kept")
            stats["conflict"] += 1
        else:
            stats["duplicate"] += 1
    if page.index not in drawing.vision_pages:
        drawing.vision_pages.append(page.index)
    # Title fields the text layer did not find.
    for a in drawing.annotations:
        if a.kind == "title_field" and a.source == "vision" and a.page == page.index:
            f = a.data.get("field")
            if f and f != "other" and (f not in drawing.title or not drawing.title[f].text):
                drawing.title[f] = a
    return stats


# ------------------------------------------------------------------ entry

def read_page_image(path: str | Path, page: Page, model: str = DEFAULT_MODEL) -> tuple[list[Annotation], dict]:
    dpi = DPI
    longest = max(page.width, page.height) / 72 * dpi
    if longest > MAX_SIDE:
        dpi = int(dpi * MAX_SIDE / longest)
    png, _ = render_page(path, page.index, dpi=dpi)
    result, usage = call_gemini(png, model)
    anns = [a for a in (to_annotation(it, page) for it in result.get("annotations", [])) if a is not None]
    return anns, usage


def extract(drawing: Drawing, path: str | Path, pages: list[int], model: str = DEFAULT_MODEL) -> Drawing:
    _api_key()   # fail before rendering anything
    totals = {"model": model, "pages": 0, "seconds": 0.0, "input_tokens": 0, "output_tokens": 0, "cached_pages": 0,
              "confirmed": 0, "conflict": 0, "vision_only": 0, "duplicate": 0}
    failed = 0
    for i in pages:
        page = drawing.pages[i]
        try:
            anns, usage = read_page_image(path, page, model)
        except VisionUnavailable as e:
            # One page failing must not cost the others; this page stays unread (RD-001).
            drawing.warnings.append(f"page {i + 1}: vision reader failed: {str(e)[:200]}")
            failed += 1
            continue
        st = merge(drawing, page, anns)
        totals["pages"] += 1
        totals["seconds"] = round(totals["seconds"] + usage.get("seconds", 0), 1)
        totals["model"] = usage.get("model", model)
        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        totals["cached_pages"] += int(usage.get("cached", False))
        for k, v in st.items():
            totals[k] += v
    totals["failed_pages"] = failed
    drawing.vision_stats = totals
    drawing.extractors.append(f"vision:{model}")
    return drawing
