"""BOM <-> CAD reconciliation.

Rows are matched to CAD parts cheapest-first: exact on a normalised key, then
fuzzy (rapidfuzz), and only the leftovers go to the LLM. Quantities are then
compared by counting placed instances — plain arithmetic, never the model.

The LLM may only pair a row index it was sent with a CAD name it was sent;
anything else is dropped, so it cannot invent a part. A pair it is unsure of
(confidence 0.5-0.8) is not used for counting; it becomes an info finding
asking the user to confirm.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import Finding, Instance, Part
from .rules.checks import is_hardware

try:
    from rapidfuzz import fuzz

    def _score(a: str, b: str) -> float:
        return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
except ImportError:                                             # pragma: no cover
    from difflib import SequenceMatcher

    def _score(a: str, b: str) -> float:
        return 100 * max(SequenceMatcher(None, a, b).ratio(),
                         SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio())

FUZZY_MIN = 90
LLM_ACCEPT = 0.8
LLM_ASK = 0.5

#: Header spellings seen in Onshape, SolidWorks, Fusion and hand-made BOMs.
COLUMNS = {
    "part_number": ["part number", "part no", "part no.", "part #", "pn", "p/n", "part_number", "partnumber",
                    "item number", "number", "sku", "mpn"],
    "name": ["name", "part name", "description", "title", "component", "part", "item", "desc"],
    "quantity": ["quantity", "qty", "qty.", "count", "amount", "qnty", "no. of parts"],
    "revision": ["revision", "rev", "rev."],
    "material": ["material", "mat", "material name"],
    "type": ["type", "make/buy", "make buy", "category", "source", "procurement"],
}


@dataclass
class BomRow:
    index: int
    part_number: str
    name: str
    quantity: Optional[float]
    revision: str = ""
    material: str = ""
    type: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.part_number or self.name

    @property
    def title(self) -> str:
        return " ".join(x for x in (self.part_number, self.name) if x)

    def to_dict(self) -> dict:
        return {"row": self.index, "part_number": self.part_number, "name": self.name,
                "quantity": self.quantity, "revision": self.revision, "material": self.material}


def norm(s: str) -> str:
    """Compact key: lowercase, no extension, no separators."""
    s = str(s or "").lower().strip()
    s = re.sub(r"\.(step|stp|sldprt|sldasm|ipt|iam|f3d|prt|fcstd)$", "", s)
    s = re.sub(r"\s*(<\d+>|\(\d+\))$", "", s)
    return re.sub(r"[\s_\-./]+", "", s)


def norm_loose(s: str) -> str:
    """Also drop a short copy suffix ('_1', '-2') that is not part of a number."""
    s = str(s or "").lower().strip()
    s = re.sub(r"(?<=[a-z])_\d{1,2}$|(?<=[a-z])[- ]\d$", "", s)
    return norm(s)


def tokens(s: str) -> str:
    s = str(s or "").lower()
    s = re.sub(r"\.(step|stp|sldprt|ipt)$", "", s)
    return " ".join(re.split(r"[\s_\-./]+", s)).strip()


def _quantity(v: str) -> Optional[float]:
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


def read_bom(path: str | Path) -> list[BomRow]:
    return parse_bom(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


def parse_bom(text: str) -> list[BomRow]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    col = {}
    for key, names in COLUMNS.items():
        for i, h in enumerate(header):
            if h in names and i not in col.values():
                col[key] = i
                break
    if "name" not in col and "part_number" not in col:
        raise ValueError(f"BOM has no part number or name column (header: {rows[0]})")

    def cell(r, key):
        i = col.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    out = []
    for k, r in enumerate(rows[1:]):
        extra = {header[i]: v for i, v in enumerate(r) if i < len(header) and i not in col.values() and v.strip()}
        out.append(BomRow(k, cell(r, "part_number"), cell(r, "name"), _quantity(cell(r, "quantity")),
                          cell(r, "revision"), cell(r, "material"), cell(r, "type"), extra))
    return [r for r in out if r.label]


@dataclass
class BomResult:
    pairs: dict[int, str]                       # bom row -> part_id
    how: dict[int, str]                         # bom row -> exact | fuzzy | llm
    findings: list[Finding]
    cad_counts: dict[str, int]
    materials: dict[str, str]                   # part_id -> material from the BOM


def reconcile(rows: list[BomRow], parts: dict[str, Part], instances: list[Instance],
              llm_match=None) -> BomResult:
    counts = Counter(i.part_id for i in instances)
    paths: dict[str, list[str]] = {}
    for i in instances:
        paths.setdefault(i.part_id, []).append(i.path)
    names = {pid: parts[pid].name for pid in counts}

    left_cad = set(counts)
    pairs: dict[int, str] = {}
    how: dict[int, str] = {}
    left_rows: list[BomRow] = []

    exact: dict[str, str] = {}
    for pid, n in names.items():
        exact.setdefault(norm(n), pid)
    loose: dict[str, set[str]] = {}
    for pid, n in names.items():
        loose.setdefault(norm_loose(n), set()).add(pid)
    for key, pids in loose.items():
        if len(pids) == 1:                  # a loose key two parts share identifies neither
            exact.setdefault(key, next(iter(pids)))
    for row in rows:
        hit = None
        for key in (norm(row.part_number), norm(row.name), norm_loose(row.part_number), norm_loose(row.name)):
            if key and key in exact and exact[key] in left_cad:
                hit = exact[key]
                break
        if hit:
            pairs[row.index], how[row.index] = hit, "exact"
            left_cad.discard(hit)
        else:
            left_rows.append(row)

    still: list[BomRow] = []
    for row in left_rows:
        cands = sorted(((max(_score(tokens(row.part_number), tokens(names[pid])) if row.part_number else 0,
                             _score(tokens(row.name), tokens(names[pid])) if row.name else 0), pid)
                        for pid in left_cad), reverse=True)
        if cands and cands[0][0] >= FUZZY_MIN and (len(cands) == 1 or cands[0][0] - cands[1][0] >= 5):
            pairs[row.index], how[row.index] = cands[0][1], "fuzzy"
            left_cad.discard(cands[0][1])
        else:
            still.append(row)

    findings: list[Finding] = []
    unsure: dict[int, tuple[str, float]] = {}
    if still and left_cad and llm_match is not None:
        cad_names = sorted(names[pid] for pid in left_cad)
        by_name = {names[pid]: pid for pid in left_cad}
        sent = {r.index for r in still}
        for bom_idx, cad_name, conf in llm_match(still, cad_names):
            if bom_idx not in sent or cad_name not in by_name:
                continue                                    # never trust an invented row or part
            pid = by_name[cad_name]
            if pid not in left_cad or bom_idx in pairs:
                continue
            if conf >= LLM_ACCEPT:
                pairs[bom_idx], how[bom_idx] = pid, "llm"
                left_cad.discard(pid)
            elif conf >= LLM_ASK:
                unsure[bom_idx] = (pid, conf)

    by_index = {r.index: r for r in rows}
    for idx, pid in pairs.items():
        row = by_index[idx]
        n = counts[pid]
        if row.quantity is not None and abs(row.quantity - n) > 1e-6:
            findings.append(Finding(
                "BOM_QTY_MISMATCH", "high", paths[pid][:10],
                f"BOM row {idx + 2} '{row.title}' orders {row.quantity:g}, the assembly places {n} "
                f"of '{names[pid]}'.",
                measured={"cad_count": n}, expected={"bom_quantity": row.quantity},
                parts=[names[pid]], source="bom",
                assumptions=[f"matched by {how[idx]}"]))
    for pid in sorted(left_cad, key=lambda p: names[p]):
        hw = is_hardware(names[pid])
        hint = next((f" Possibly BOM row {i + 2} '{by_index[i].label}' (unconfirmed match)."
                     for i, (p, _) in unsure.items() if p == pid), "")
        findings.append(Finding(
            "IN_CAD_NOT_BOM", "low" if hw else "high", paths[pid][:10],
            f"'{names[pid]}' ({counts[pid]} in the assembly) has no BOM row.{hint}",
            measured={"cad_count": counts[pid]}, parts=[names[pid]], source="bom"))
    for row in rows:
        if row.index in pairs:
            continue
        hw = is_hardware(row.title) or bool(re.search(r"cable|wire|glue|loctite|tape|zip\s?tie|grease|label",
                                                     row.title, re.I))
        hint = ""
        if row.index in unsure:
            pid, conf = unsure[row.index]
            hint = f" Possibly '{names[pid]}' (confidence {conf:.2f})."
            findings.append(Finding(
                "LOW_CONFIDENCE_MATCH", "info", paths[pid][:10],
                f"BOM row {row.index + 2} '{row.title}' may be CAD part '{names[pid]}' "
                f"(model confidence {conf:.2f}). Confirm to include it in the quantity check.",
                measured={"confidence": conf}, parts=[names[pid]], source="llm"))
        findings.append(Finding(
            "IN_BOM_NOT_CAD", "low" if hw else "medium", [],
            f"BOM row {row.index + 2} '{row.title}' (qty {row.quantity if row.quantity is not None else '?'}) "
            f"has no part in the assembly.{hint}",
            expected={"bom_quantity": row.quantity}, parts=[row.name or row.label], source="bom"))

    materials = {pid: by_index[i].material for i, pid in pairs.items() if by_index[i].material}
    return BomResult(pairs, how, findings, dict(counts), materials)
