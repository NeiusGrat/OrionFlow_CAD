"""Revision diff, change impact, and drawings that went stale.

XCAF label ids are not stable between exports, so parts are matched across
revisions by normalised name, then — for renamed parts — by geometric
signature (volume, area, bounding box, hole count, all within 1%). What is
left over was added or removed.

Change impact uses the interface graph of the new revision: a changed part's
neighbours "need a look", and every finding is labelled new / unchanged by its
fingerprint (rule + part names + location), with the old revision's findings
that disappeared reported as fixed.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .bom import norm
from .features import axis_offset, parallel
from .ingest_step import same_signature
from .models import Features, Finding

RESIZE_REL = 0.005
HOLE_TOL = 0.05
PATTERN_TOL = 0.1


@dataclass
class PartChange:
    part: str
    status: str                         # changed | added | removed | renamed | moved
    old_name: str = ""
    details: list[str] = field(default_factory=list)
    interface_changed: bool = False     # holes / patterns, i.e. what mates
    neighbours: list[str] = field(default_factory=list)
    instances: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def match_parts(old, new) -> tuple[dict[str, str], list[str], list[str]]:
    """new part_id -> old part_id, plus unmatched new and old ids."""
    pairs: dict[str, str] = {}
    old_by_name: dict[str, str] = {}
    for pid, p in old.parts.items():
        old_by_name.setdefault(norm(p.name), pid)
    left_old = set(old.parts)
    for pid, p in new.parts.items():
        o = old_by_name.get(norm(p.name))
        if o in left_old:
            pairs[pid] = o
            left_old.discard(o)
    for pid in [p for p in new.parts if p not in pairs]:
        fn = new.part_feats[pid]
        for o in sorted(left_old):
            fo = old.part_feats[o]
            if same_signature(new.parts[pid].signature, old.parts[o].signature) and len(fn.holes) == len(fo.holes):
                pairs[pid] = o
                left_old.discard(o)
                break
    added = [p for p in new.parts if p not in pairs]
    return pairs, added, sorted(left_old)


def _hole_changes(fo: Features, fn: Features) -> list[str]:
    out = []
    used = set()
    for h in fn.holes:
        best, off = None, 1e9
        for k, o in enumerate(fo.holes):
            if k in used or not parallel(h.axis, o.axis):
                continue
            d = axis_offset(o, h.center)
            if d < off:
                best, off = k, d
        if best is None or off > max(h.diameter, fo.holes[best].diameter):
            out.append(f"hole added Ø{h.diameter:.2f} at {np.round(h.center, 2).tolist()}")
            continue
        used.add(best)
        o = fo.holes[best]
        if off > HOLE_TOL:
            out.append(f"hole Ø{h.diameter:.2f} moved {off:.2f} mm")
        if abs(o.diameter - h.diameter) > HOLE_TOL:
            out.append(f"hole resized Ø{o.diameter:.2f} -> Ø{h.diameter:.2f}")
    for k, o in enumerate(fo.holes):
        if k not in used:
            out.append(f"hole removed Ø{o.diameter:.2f} at {np.round(o.center, 2).tolist()}")
    return out


def _pattern_changes(fo: Features, fn: Features) -> list[str]:
    out = []
    for p in fn.patterns:
        if p.kind == "group":
            continue
        cands = [o for o in fo.patterns if o.kind == p.kind and len(o.holes) == len(p.holes)
                 and parallel(o.axis, p.axis)]
        if not cands:
            continue
        o = min(cands, key=lambda o: np.linalg.norm(o.centroid - p.centroid))
        if p.kind == "circle" and abs(o.pcd - p.pcd) > PATTERN_TOL:
            out.append(f"bolt circle changed {o.pcd:.2f} -> {p.pcd:.2f} mm")
        if p.kind == "rect" and abs(o.a - p.a) + abs(o.b - p.b) > PATTERN_TOL:
            out.append(f"hole rectangle changed {o.a:.2f}x{o.b:.2f} -> {p.a:.2f}x{p.b:.2f} mm")
    return out


def diff(old, new) -> list[PartChange]:
    pairs, added, removed = match_parts(old, new)
    graph = new.graph()
    by_part: dict[str, list] = {}
    for i in new.instances:
        by_part.setdefault(i.part_id, []).append(i)
    old_by_part: dict[str, list] = {}
    for i in old.instances:
        old_by_part.setdefault(i.part_id, []).append(i)

    changes: list[PartChange] = []
    for pid, opid in pairs.items():
        fn, fo = new.part_feats[pid], old.part_feats[opid]
        details: list[str] = []
        sn, so = new.parts[pid].signature, old.parts[opid].signature
        if abs(sn["volume"] - so["volume"]) > RESIZE_REL * max(so["volume"], 1e-9) or any(
                abs(a - b) > RESIZE_REL * max(b, 1e-9) for a, b in zip(sn["bbox"], so["bbox"])):
            details.append(f"resized: volume {so['volume']:.0f} -> {sn['volume']:.0f} mm³, "
                           f"box {so['bbox']} -> {sn['bbox']}")
        holes = _hole_changes(fo, fn)
        pats = _pattern_changes(fo, fn)
        details += pats + holes
        ni, oi = by_part.get(pid, []), old_by_part.get(opid, [])
        if len(ni) != len(oi):
            details.append(f"instance count {len(oi)} -> {len(ni)}")
        for a, b in zip(sorted(ni, key=lambda i: i.path), sorted(oi, key=lambda i: i.path)):
            if not np.allclose(a.transform, b.transform, atol=1e-3):
                shift = np.linalg.norm(a.transform[:3, 3] - b.transform[:3, 3])
                details.append(f"{a.path} moved in the assembly ({shift:.2f} mm)")
        renamed = norm(new.parts[pid].name) != norm(old.parts[opid].name)
        if not details and not renamed:
            continue
        ch = PartChange(new.parts[pid].name, "changed" if details else "renamed", old.parts[opid].name, details,
                        interface_changed=bool(holes or pats or any("moved" in d for d in details)),
                        instances=[i.path for i in ni])
        changes.append(ch)
    for pid in added:
        changes.append(PartChange(new.parts[pid].name, "added", interface_changed=True,
                                  instances=[i.path for i in by_part.get(pid, [])]))
    for opid in removed:
        changes.append(PartChange(old.parts[opid].name, "removed", interface_changed=True,
                                  instances=[i.path for i in old_by_part.get(opid, [])]))

    name_of = {i.instance_id: new.parts[i.part_id].name for i in new.instances}
    for ch in changes:
        if ch.status == "removed":
            continue
        ids = [i.instance_id for i in new.instances if new.parts[i.part_id].name == ch.part]
        neigh = {name_of[n] for iid in ids for n in graph.get(iid, ())} - {ch.part}
        ch.neighbours = sorted(neigh)
    return changes


def label_findings(old_findings: list[Finding], new_findings: list[Finding]) -> list[Finding]:
    """Mark new/unchanged on the new findings; return the old ones that went away."""
    old = {f.fingerprint: f for f in old_findings}
    new = {f.fingerprint for f in new_findings}
    for f in new_findings:
        f.change_status = "unchanged" if f.fingerprint in old else "new"
    fixed = []
    for fp, f in old.items():
        if fp not in new:
            f.change_status = "fixed"
            fixed.append(f)
    return fixed


# ------------------------------------------------------------------ drawings

_REV = re.compile(r"\bREV(?:ISION)?\.?\s*[:#]?\s*([A-Z]{1,2}|\d{1,2})\b")


def read_drawings(paths: list[Path], candidates: dict[str, str], llm=None) -> list[dict]:
    """Drawing -> part. ``candidates`` maps searchable number/name -> part name."""
    import pymupdf

    out = []
    keys = sorted(candidates, key=len, reverse=True)
    for p in paths:
        text = "\n".join(pg.get_text() for pg in pymupdf.open(str(p)))
        compact = norm(text)
        part = next((candidates[k] for k in keys if len(norm(k)) >= 3 and norm(k) in compact), None)
        how = "text"
        if part is None and llm is not None and getattr(llm, "available", False):
            from .llm import drawing_part
            try:
                ans = drawing_part(llm, text, keys)
                if ans.get("part_number") in candidates:            # guard: must be one we sent
                    part, how = candidates[ans["part_number"]], "llm"
            except Exception:  # noqa: BLE001 - an unreadable drawing is reported, not fatal
                part = None
        m = _REV.search(text.upper())
        out.append({"file": Path(p).name, "part": part, "revision": m.group(1) if m else None, "matched_by": how})
    return out


def drawing_findings(drawings: list[dict], changes: list[PartChange], bom_revisions: dict[str, str]
                     ) -> list[Finding]:
    findings = []
    changed = {c.part: c for c in changes if c.status in ("changed", "renamed")}
    touched: dict[str, str] = {}
    for c in changes:
        if c.interface_changed:
            for n in c.neighbours:
                touched.setdefault(n, c.part)
    for d in drawings:
        part = d["part"]
        if part is None:
            findings.append(Finding("DRAWING_UNMATCHED", "info", [], f"Drawing {d['file']} names no part in the "
                                    "BOM or assembly; it was not checked.", parts=[d["file"]], source="revision"))
            continue
        if part in changed:
            findings.append(Finding(
                "DRAWING_STALE", "high", changed[part].instances[:5],
                f"Drawing {d['file']} is of {part}, which changed in this revision: "
                f"{'; '.join(changed[part].details[:3])}.", parts=[part, d["file"]], source="revision"))
        elif part in touched:
            findings.append(Finding(
                "DRAWING_STALE", "medium", [],
                f"Drawing {d['file']} is of {part}, whose mating part {touched[part]} changed an interface; "
                "check the shared features.", parts=[part, d["file"]], source="revision"))
        bom_rev = bom_revisions.get(part)
        if bom_rev and d["revision"] and bom_rev.strip().upper() != d["revision"].strip().upper():
            findings.append(Finding(
                "DRAWING_REV_MISMATCH", "medium", [],
                f"Drawing {d['file']} shows revision {d['revision']}, the BOM lists {part} at {bom_rev}.",
                measured={"drawing_rev": d["revision"]}, expected={"bom_rev": bom_rev},
                parts=[part, d["file"]], source="revision"))
    return findings
