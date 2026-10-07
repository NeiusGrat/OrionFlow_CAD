"""BOM files -> rows -> matched to CAD parts, with quantities, materials and mass.

Reads CSV/TSV, XLSX and Markdown pipe tables. The header row is found by
scoring the first rows against known column spellings, because real BOMs put
titles, blank lines and logos above it (the YUBI BOM has a title row, a
separator and an empty row first).

Matching, cheapest first, each pair labelled with how it was made:

  exact   normalised part number, name or file name equals the CAD part name
  fuzzy   rapidfuzz >= 90 with a clear margin over the runner-up
  ai      the LLM, shown only the leftover rows and leftover CAD names, may
          return only ids it was sent (anything else is dropped)
  human   the engineer's own pairing, which overrides all of the above

Several rows may name one CAD part (the YUBI BOM lists a locating pin once for
the gripper and again for the UR5e mount): quantities are summed per part
before they are compared with the CAD count — plain arithmetic.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from interface_check.bom import COLUMNS as IC_COLUMNS
from interface_check.bom import _score, norm, norm_loose, tokens

from .materials import density, process_from_type

COLUMNS = {k: list(v) for k, v in IC_COLUMNS.items()}
COLUMNS["file"] = ["file", "file name", "filename", "cad file", "model", "file name (stl/step)", "step file"]
FUZZY_MIN = 90
FUZZY_MARGIN = 5


def score(a: str, b: str) -> float:
    """rapidfuzz ratio / token-sort, plus token-set for a name that is the other with a prefix dropped.

    "FINGER PAD_t30_R" vs "PAD_t30_R": every token of the shorter is in the longer. Token-set counts only
    when the shorter has at least two tokens and one of the shared tokens is specific (has a digit, or is
    four letters or more), so "PAD" alone can never match "FINGER PAD".
    """
    from rapidfuzz import fuzz

    ta, tb = tokens(a), tokens(b)
    base = _score(ta, tb)
    sa, sb = set(ta.split()), set(tb.split())
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if len(small) >= 2 and small <= big and any(re.search(r"\d", t) or len(t) >= 4 for t in small):
        base = max(base, float(fuzz.token_set_ratio(ta, tb)))
    return base


@dataclass
class Row:
    file: str                       # source BOM file name
    index: int                      # data row number in that file, 1-based (what an engineer sees)
    part_number: str = ""
    name: str = ""
    quantity: Optional[float] = None
    material: str = ""
    type: str = ""
    cad_file: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.file}#{self.index}"

    @property
    def label(self) -> str:
        return self.part_number or self.name or self.cad_file


# ------------------------------------------------------------------- parse --

def _cells_md(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [re.sub(r"\[([^\]]*)\]\(([^)]*)\)", lambda m: m.group(1) or m.group(2), c).strip() for c in s.split("|")]


def _table(name: str, data: bytes) -> list[list[str]]:
    ext = Path(name).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
    text = data.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines()]
    if sum(1 for ln in lines if ln.strip().startswith("|")) >= 2:
        rows = []
        for ln in lines:
            if not ln.strip().startswith("|"):
                continue
            cells = _cells_md(ln)
            if all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells) and any(c for c in cells):
                continue                        # | --- | --- | separator
            rows.append(cells)
        return rows
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]


def _canon(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower()).strip()


def _map_header(header: list[str]) -> dict[str, int]:
    col: dict[str, int] = {}
    canon = [_canon(h) for h in header]
    for key, names in COLUMNS.items():
        for i, h in enumerate(canon):
            if i in col.values():
                continue
            if h in names or h.rstrip(".") in [n.rstrip(".") for n in names] or (key == "file" and h.startswith("file")):
                col[key] = i
                break
    return col


def parse(name: str, data: bytes) -> tuple[list[Row], dict]:
    """Rows of one BOM file, and what was read (header row, column map, rows skipped)."""
    table = [r for r in _table(name, data)]
    best, best_i, best_map = -1, -1, {}
    for i, r in enumerate(table[:25]):
        m = _map_header(r)
        score = len(m) + (2 if "quantity" in m else 0) + (2 if ("part_number" in m or "name" in m) else 0)
        if ("part_number" in m or "name" in m) and score > best:
            best, best_i, best_map = score, i, m
    if best_i < 0:
        raise ValueError(f"{name}: no header row with a part number or name column in the first 25 rows")
    header = table[best_i]
    rows: list[Row] = []
    skipped = 0
    n = 0
    for r in table[best_i + 1:]:
        if not any(c for c in r):
            continue
        def cell(k):
            i = best_map.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        pn, nm, cf = cell("part_number"), cell("name"), cell("file")
        qty_txt = cell("quantity")
        m = re.search(r"\d+(?:\.\d+)?", qty_txt)
        qty = float(m.group()) if m else None
        if not (pn or nm or cf) or (qty is None and not pn and len(" ".join(r)) > 80):
            skipped += 1                        # footers, notes, disclaimers
            continue
        n += 1
        extra = {_canon(header[i]): v for i, v in enumerate(r) if i < len(header) and i not in best_map.values() and v}
        rows.append(Row(name, n, pn, nm, qty, cell("material"), cell("type"), cf, extra))
    info = {"file": name, "header_row": best_i + 1, "columns": {k: header[i] for k, i in best_map.items()},
            "rows": len(rows), "skipped": skipped}
    return rows, info


# --------------------------------------------------------------- reconcile --

def reconcile(rows: list[Row], graph, llm_match=None, human: dict[str, Optional[str]] | None = None,
              prior: dict[str, tuple] | None = None) -> list[dict]:
    """Match every row to a CAD part id (or None). Returns row records ready for ``graph.bom_rows``.

    ``prior`` carries earlier AI matches forward when only a human link changed, so editing one row never
    sends the BOM to the model again.
    """
    human = human or {}
    prior = prior or {}
    names = {p.id: p.name for p in graph.parts}
    exact: dict[str, set[str]] = defaultdict(set)
    for pid, n in names.items():
        exact[norm(n)].add(pid)
        exact[norm_loose(n)].add(pid)
    match: dict[str, tuple[Optional[str], str, float]] = {}
    for r in rows:
        if r.key in human:
            match[r.key] = (human[r.key], "human", 1.0)
            continue
        if r.key in prior:
            match[r.key] = prior[r.key]
            continue
        for k in (r.part_number, r.cad_file, r.name):
            for key in (norm(k), norm_loose(k)):
                if key and len(exact.get(key, ())) == 1:
                    match[r.key] = (next(iter(exact[key])), "exact", 1.0)
                    break
            if r.key in match:
                break
    taken = {m[0] for m in match.values() if m[0]}
    left = [r for r in rows if r.key not in match]
    pool = [pid for pid in names if pid not in taken]
    still = []
    for r in left:
        cands = sorted(((max(score(x, names[pid]) for x in (r.part_number, r.cad_file, r.name) if x), pid)
                        for pid in pool), reverse=True) if pool else []
        if cands and cands[0][0] >= FUZZY_MIN and (len(cands) == 1 or cands[0][0] - cands[1][0] >= FUZZY_MARGIN):
            match[r.key] = (cands[0][1], "fuzzy", round(cands[0][0] / 100, 3))
            pool.remove(cands[0][1])
        else:
            still.append(r)
    if still and pool and llm_match is not None:
        by_name = {names[pid]: pid for pid in pool}
        sent = {r.key for r in still}
        for key, cad_name, conf in llm_match(still, sorted(by_name)):
            if key not in sent or cad_name not in by_name or key in match:
                continue                        # never accept an invented row or part
            match[key] = (by_name[cad_name], "ai", round(float(conf), 3))
    out = []
    for r in rows:
        pid, how, conf = match.get(r.key, (None, "none", 0.0))
        rho, why = density(r.material)
        out.append({
            "key": r.key, "file": r.file, "row": r.index, "part_number": r.part_number, "name": r.name,
            "quantity": r.quantity, "material": r.material, "type": r.type, "cad_file": r.cad_file, "extra": r.extra,
            "part_id": pid, "method": how, "confidence": conf, "process": process_from_type(r.type),
            "density": rho, "density_note": why,
        })
    return out


def apply(graph, records: list[dict]) -> None:
    """Write matched rows into the graph and give matched parts their material, process and mass."""
    graph.bom_rows = records
    by_part: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if rec["part_id"] and rec["method"] in ("exact", "fuzzy", "human", "ai"):
            by_part[rec["part_id"]].append(rec)
    for p in graph.parts:
        recs = by_part.get(p.id, [])
        mats = sorted({r["material"] for r in recs if r["material"]})
        procs = sorted({r["process"] for r in recs if r["process"]})
        p.material = mats[0] if len(mats) == 1 else (" | ".join(mats) if mats else None)
        p.process = procs[0] if len(procs) == 1 else (" | ".join(procs) if procs else None)
        rho = recs[0]["density"] if len(mats) == 1 and recs and recs[0]["density"] else None
        p.mass = round(p.volume * 1e-9 * rho, 6) if rho else None


def match_with_llm(llm, job_logger=None):
    """Adapter: the gateway's strict-JSON BOM matcher, rows keyed by Row.key."""
    if llm is None or not getattr(llm, "available", False):
        return None

    def run(rows: list[Row], cad_names: list[str]):
        from interface_check.llm import match_bom

        class _R:                               # interface_check's matcher indexes rows by position
            def __init__(self, i, r):
                self.index, self.part_number, self.name, self.title = i, r.part_number, r.name, f"{r.part_number} {r.name}".strip()
                self.label, self.quantity = r.label, r.quantity
        shim = [_R(i, r) for i, r in enumerate(rows)]
        out = []
        for i, cad, conf in match_bom(llm, shim, cad_names):
            if 0 <= i < len(rows):
                out.append((rows[i].key, cad, conf))
        return out
    return run


def rows_from_records(records: list[dict]) -> list[Row]:
    return [Row(r["file"], r["row"], r["part_number"], r["name"], r["quantity"], r["material"], r["type"],
                r.get("cad_file", ""), r.get("extra") or {}) for r in records]


def export_rows(graph) -> list[dict]:
    """The reconciled BOM: every BOM row with its CAD part and count, then every CAD part the BOM lacks."""
    names = {p.id: p for p in graph.parts}
    count: dict[str, int] = defaultdict(int)
    for i in graph.instances:
        count[i.part_id] += 1
    summed: dict[str, float] = defaultdict(float)
    for r in graph.bom_rows:
        if r["part_id"] and r["quantity"] is not None and r["method"] != "none":
            summed[r["part_id"]] += r["quantity"]
    out = []
    for r in graph.bom_rows:
        p = names.get(r["part_id"]) if r["part_id"] else None
        status = ("unmatched" if not p else "ok" if r["quantity"] is None or abs(summed[p.id] - count[p.id]) < 1e-6
                  else "quantity differs")
        out.append({"bom_file": r["file"], "bom_row": r["row"], "part_number": r["part_number"], "name": r["name"],
                    "bom_qty": r["quantity"], "cad_part": p.name if p else "", "cad_qty": count[p.id] if p else "",
                    "match": r["method"], "confidence": r["confidence"], "material": r["material"],
                    "process": r["process"] or "", "density_kg_m3": r["density"] or "",
                    "unit_mass_kg": p.mass if p and p.mass is not None else "", "status": status})
    matched = {r["part_id"] for r in graph.bom_rows if r["part_id"]}
    for p in graph.parts:
        if p.id not in matched:
            out.append({"bom_file": "", "bom_row": "", "part_number": "", "name": "", "bom_qty": "", "cad_part": p.name,
                        "cad_qty": count[p.id], "match": "none", "confidence": "", "material": "", "process": "",
                        "density_kg_m3": "", "unit_mass_kg": "", "status": "not in BOM"})
    return out
