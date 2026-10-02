"""The checks. Each takes a read Drawing and yields hits; rules.yaml says what
a hit means to a reviewer and what to ask the customer.

Two kinds of rule:
  presence   something on the drawing is wrong (a frame, a fit, a thread).
             The finding points at the callout and carries its text.
  absence    something required is not on the drawing (no material, no
             general tolerance). Only as good as the reader: if a page could
             not be read, an absence is not proven, and the finding says so.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator

import yaml

from . import parse
from .model import Annotation, Drawing, Finding

RULES_FILE = Path(__file__).with_name("rules.yaml")


@dataclass
class Hit:
    rule: str
    ann: Annotation | None = None
    value: str = ""
    evidence: str = ""
    page: int | None = None


Check = Callable[[Drawing], Iterator[Hit]]
REGISTRY: dict[str, Check] = {}
ABSENCE: set[str] = set()


def rule(*ids: str, absence: bool = False):
    def deco(fn: Check) -> Check:
        for i in ids:
            REGISTRY[i] = fn
            if absence:
                ABSENCE.add(i)
        return fn
    return deco


@lru_cache(maxsize=4)
def load_rules(path: str = str(RULES_FILE)) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]


# ------------------------------------------------------------------ helpers

def _notes(d: Drawing) -> list[Annotation]:
    return d.of("note")


def _title_value(d: Drawing, field: str) -> str:
    a = d.title.get(field)
    return a.text.strip() if a else ""


def _general_tolerances(d: Drawing) -> list[tuple[Annotation, dict]]:
    out = [(a, a.data["general_tolerance"]) for a in _notes(d) if a.data.get("general_tolerance")]
    tol = d.title.get("tolerance")
    if tol and tol.text:
        gt = parse.parse_general_tolerance(tol.text) or (
            {"standard": "block", "linear_class": None, "geometric_class": None} if "±" in tol.text else None)
        if gt:
            out.append((tol, gt))
    return out


def _standards(d: Drawing) -> dict[str, Annotation]:
    out: dict[str, Annotation] = {}
    for a in _notes(d):
        for s in a.data.get("standards", []):
            out.setdefault(s["standard"], a)
    return out


def _units(d: Drawing) -> str | None:
    u = _title_value(d, "units")
    if u:
        return parse.parse_units(u) or parse.parse_units("UNITS " + u)
    for a in _notes(d):
        if a.data.get("units"):
            return a.data["units"]
    return None


def _frames(d: Drawing) -> list[Annotation]:
    return [a for a in d.of("gdt_frame") if not a.data.get("unparsed")]


def _datum_defs(d: Drawing) -> dict[str, list[Annotation]]:
    out: dict[str, list[Annotation]] = defaultdict(list)
    for a in d.of("datum_feature"):
        out[a.data["letter"]].append(a)
    return out


# ------------------------------------------------------------------ title block

@rule("TB-001", absence=True)
def _no_title(d: Drawing):
    if not d.title:
        yield Hit("TB-001")


@rule("TB-002", "TB-003", "TB-004", "TB-005", "TB-006", absence=True)
def _title_fields(d: Drawing):
    if not d.title:
        return
    if not (_title_value(d, "drawing_number") or _title_value(d, "part_number")):
        yield Hit("TB-002")
    if not _title_value(d, "revision"):
        yield Hit("TB-003")
    material = _title_value(d, "material")
    if not material and not any("MATERIAL" in a.text.upper() for a in _notes(d)):
        yield Hit("TB-004")
    if not _title_value(d, "scale"):
        yield Hit("TB-005")
    if not _title_value(d, "approved_by"):
        yield Hit("TB-006")


@rule("TB-007")
def _heat_treat(d: Drawing):
    sources = list(_notes(d))
    for f in ("finish", "material"):
        if f in d.title:
            a = d.title[f]
            sources.append(Annotation("note", a.text, a.page, a.bbox, a.source,
                                      {"heat_treatment": True} if parse_ht(a.text) else {}))
    hard_anywhere = any(a.data.get("hardness") for a in sources) or any(
        has_hardness(a.text) for a in sources)
    for a in sources:
        if a.data.get("heat_treatment") and not a.data.get("hardness") and not hard_anywhere:
            yield Hit("TB-007", a, evidence=a.text)


def parse_ht(text: str) -> bool:
    return bool(re.search(r"\b(HARDEN|CASE\s+HARDEN|CARBURI[SZ]E|NITRIDE|INDUCTION|QUENCH|HEAT\s+TREAT)", text.upper()))


def has_hardness(text: str) -> bool:
    return bool(re.search(r"\b\d{2,3}\s*(?:-\s*\d{2,3}\s*)?(HRC|HRB|HB|HBW|HV)\b|\b(HRC|HB|HV)\s*\d", text.upper()))


# ------------------------------------------------------------------ general tolerance / standards

def _untoleranced(d: Drawing) -> list[Annotation]:
    return [a for a in d.of("dimension")
            if a.data.get("tol_type") == "none" and not a.data.get("reference") and not a.data.get("basic")]


@rule("GT-001", absence=True)
def _no_general_tol(d: Drawing):
    if _general_tolerances(d):
        return
    loose = _untoleranced(d)
    if loose:
        yield Hit("GT-001", value=str(len(loose)))


@rule("GT-002")
def _iso2768_class(d: Drawing):
    for a, gt in _general_tolerances(d):
        if gt["standard"] == "ISO 2768" and not gt["linear_class"]:
            yield Hit("GT-002", a, evidence=a.text)


@rule("GT-003", absence=True)
def _gdt_standard(d: Drawing):
    if not d.of("gdt_frame"):
        return
    stds = _standards(d)
    if not ({"ASME Y14.5", "ISO 1101", "ISO 8015", "BS 8888"} & stds.keys()):
        yield Hit("GT-003")


@rule("GT-004")
def _mixed_standards(d: Drawing):
    stds = _standards(d)
    iso = [s for s in ("ISO 8015", "ISO 2768", "ISO 1101", "IS 2102") if s in stds]
    if "ASME Y14.5" in stds and iso:
        yield Hit("GT-004", stds["ASME Y14.5"], value="ASME Y14.5 + " + ", ".join(iso),
                  evidence=stds["ASME Y14.5"].text)


# ------------------------------------------------------------------ projection / units

@rule("PR-001", absence=True)
def _projection(d: Drawing):
    if not d.of("projection") and not _title_value(d, "projection"):
        yield Hit("PR-001")


@rule("PR-002")
def _projection_conflict(d: Drawing):
    methods = {a.data["method"] for a in d.of("projection")}
    tp = parse.parse_projection(_title_value(d, "projection")) if _title_value(d, "projection") else None
    if tp:
        methods.add(tp)
    if "both" in methods or {"first", "third"} <= methods:
        ev = "; ".join(a.text for a in d.of("projection"))
        yield Hit("PR-002", (d.of("projection") or [None])[0], evidence=ev)


@rule("UN-001", absence=True)
def _units_stated(d: Drawing):
    if _units(d) is None and d.of("dimension"):
        yield Hit("UN-001")


@rule("UN-002")
def _leading_zero(d: Drawing):
    if _units(d) != "mm":
        return
    for a in d.of("dimension"):
        if a.data.get("raw_nominal", "").startswith("."):
            yield Hit("UN-002", a, evidence=a.text)


# ------------------------------------------------------------------ dimensions

@rule("DM-001", "DM-003")
def _tol_limits(d: Drawing):
    for a in d.of("dimension"):
        up, lo = a.data.get("upper"), a.data.get("lower")
        if up is None or lo is None:
            continue
        if up < lo:
            yield Hit("DM-001", a, evidence=a.text)
        elif up == lo:
            yield Hit("DM-003", a, evidence=a.text)


@rule("DM-002")
def _fits(d: Drawing):
    for a in d.of("dimension"):
        fit = a.data.get("fit")
        if fit:
            problems = parse.check_fit(fit)
            if problems:
                yield Hit("DM-002", a, value="; ".join(problems), evidence=fit)


# ------------------------------------------------------------------ threads

@rule("TH-001", "TH-002", "TH-004")
def _threads(d: Drawing):
    for a in d.of("thread"):
        t = a.data
        if t["system"] == "unified" and not t.get("class"):
            yield Hit("TH-001", a, evidence=a.text)
        if t["system"] == "metric" and not t.get("class"):
            yield Hit("TH-002", a, evidence=a.text)
        # Depth only matters for internal blind threads; a callout on a hole
        # leader usually carries a drill depth. External threads have neither,
        # so only flag callouts that name an internal class (capital letter).
        internal = bool(t.get("class") and any(c.isupper() for c in t["class"]))
        if internal and t.get("depth") is None and not t.get("thru"):
            yield Hit("TH-004", a, evidence=a.text)


@rule("TH-003")
def _thread_mix(d: Drawing):
    systems = Counter(a.data["system"] for a in d.of("thread"))
    if systems.get("metric") and systems.get("unified"):
        yield Hit("TH-003", value=f"{systems['metric']} metric, {systems['unified']} unified")


# ------------------------------------------------------------------ surface finish

@rule("SF-001", absence=True)
def _finish(d: Drawing):
    if d.of("surface_finish") or _title_value(d, "finish"):
        return
    if any(a.data.get("general_finish") for a in _notes(d)):
        return
    if d.of("dimension"):
        yield Hit("SF-001")


@rule("SF-002")
def _ra_series(d: Drawing):
    for a in d.of("surface_finish"):
        if a.data.get("param") == "Ra":
            v = a.data["value"]
            if not any(abs(v - p) < 1e-9 for p in parse.RA_PREFERRED):
                yield Hit("SF-002", a, evidence=a.text)


# ------------------------------------------------------------------ GD&T

@rule("GD-001")
def _undefined_datum(d: Drawing):
    defined = _datum_defs(d)
    for a in _frames(d):
        for letter in parse.datum_letters(a.data.get("datums", [])):
            if letter not in defined:
                yield Hit("GD-001", a, value=letter, evidence=a.text)


@rule("GD-002", "GD-003", "GD-004", "GD-005")
def _datum_requirements(d: Drawing):
    for a in _frames(d):
        cat, has = a.data["category"], bool(a.data["datums"])
        if cat == "form" and has:
            yield Hit("GD-002", a, evidence=a.text)
        elif cat == "orientation" and not has:
            yield Hit("GD-003", a, evidence=a.text)
        elif a.data["characteristic"] == "position" and not has:
            yield Hit("GD-004", a, evidence=a.text)
        elif cat == "runout" and not has:
            yield Hit("GD-005", a, evidence=a.text)


#: Characteristics that never take an MMC/LMC modifier on the tolerance.
_NO_MATERIAL_MOD = {"circular_runout", "total_runout", "concentricity", "symmetry",
                    "circularity", "cylindricity", "profile_line", "profile_surface"}


@rule("GD-006")
def _material_mods(d: Drawing):
    for a in _frames(d):
        mod = a.data.get("material")
        if mod in ("M", "L") and a.data["characteristic"] in _NO_MATERIAL_MOD:
            yield Hit("GD-006", a, value={"M": "MMC", "L": "LMC"}[mod], evidence=a.text)


@rule("GD-007", "GD-008")
def _datum_letters(d: Drawing):
    for letter, anns in _datum_defs(d).items():
        # The same datum shown in several views or sheets is normal; twice on one sheet is not.
        per_page: dict[int, list[Annotation]] = defaultdict(list)
        for a in anns:
            per_page[a.page].append(a)
        for same_page in per_page.values():
            apart = [a for a in same_page[1:] if all(abs(a.bbox[0] - b.bbox[0]) + abs(a.bbox[1] - b.bbox[1]) > 30
                                                    for b in same_page[:same_page.index(a)])]
            if apart:
                yield Hit("GD-007", apart[0], value=letter, evidence=letter)
                break
        if letter in ("I", "O", "Q"):
            yield Hit("GD-008", anns[0], value=letter, evidence=letter)


@rule("GD-009")
def _zero_tol(d: Drawing):
    for a in _frames(d):
        if a.data["tolerance"] == 0 and a.data.get("material") not in ("M", "L"):
            yield Hit("GD-009", a, evidence=a.text)


@rule("GD-010")
def _unparsed_frames(d: Drawing):
    for a in d.of("gdt_frame"):
        if a.data.get("unparsed"):
            yield Hit("GD-010", a, evidence=a.text)


@rule("GD-011")
def _unused_datum(d: Drawing):
    used = {x for a in _frames(d) for x in parse.datum_letters(a.data.get("datums", []))}
    for letter, anns in _datum_defs(d).items():
        if letter not in used:
            yield Hit("GD-011", anns[0], value=letter, evidence=letter)


# ------------------------------------------------------------------ notes / reader

@rule("NT-001", absence=True)
def _edges(d: Drawing):
    if d.of("dimension") and not any(a.data.get("edge_note") for a in _notes(d)):
        yield Hit("NT-001")


@rule("RD-001")
def _unread_pages(d: Drawing):
    for p in d.pages:
        if p.scanned and p.index not in d.vision_pages:
            yield Hit("RD-001", page=p.index)


# ------------------------------------------------------------------ run

def run(d: Drawing, only: set[str] | None = None) -> list[Finding]:
    meta = load_rules()
    missing = set(REGISTRY) - set(meta)
    if missing:
        raise RuntimeError(f"rules without rules.yaml entries: {sorted(missing)}")
    # An absence is only as good as the reading: unproven if a page went unread,
    # and resting on the vision model if a page had no text layer of its own.
    unread = any(p.scanned and p.index not in d.vision_pages for p in d.pages)
    vision_read = any(p.scanned and p.index in d.vision_pages for p in d.pages)
    findings: list[Finding] = []
    seen_fns: set[Check] = set()
    for rid, fn in REGISTRY.items():
        if fn in seen_fns:
            continue
        seen_fns.add(fn)
        for h in fn(d):
            if only and h.rule not in only:
                continue
            m = meta[h.rule]
            page = h.page if h.page is not None else (h.ann.page if h.ann else None)
            evidence = h.evidence or (h.ann.text if h.ann else "")
            query = m["query"].format(evidence=evidence, value=h.value,
                                      page=(page + 1) if page is not None else "")
            if h.ann:
                confidence = h.ann.source
            elif h.rule in ABSENCE and unread:
                confidence = "partial"
            elif h.rule in ABSENCE and vision_read:
                confidence = "vision"
            else:
                confidence = "absence"
            findings.append(Finding(
                rule=h.rule, severity=m["severity"], title=m["title"],
                message=m["title"] + (f": {evidence}" if evidence else "") + (f" ({h.value})" if h.value and h.value not in evidence else ""),
                query=query, page=page, bbox=h.ann.bbox if h.ann else None,
                evidence=evidence, standard=m.get("standard", ""), clause=m.get("clause", "") or "",
                confidence=confidence,
            ))
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.page if f.page is not None else -1, f.rule))
    return findings
