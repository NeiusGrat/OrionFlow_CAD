"""Revision compare: what changed between two Model Graphs, what it breaks, and what still fits.

Everything here reads two stored graphs — no geometry is recomputed.

Part matching, in order, each match labelled with how it was made:

  name        normalised part names equal (and the shapes are not wildly different)
  signature   volume, area and sorted envelope equal within 1 % — the same part, renamed or
              in a file whose names are machine-made (a flattened export)
  shape       the same kind of part, changed: volume and every envelope side within 15 %, the best
              candidate by a clear margin; reported with its similarity, never as certain
  —           nothing matched: removed (base only) or added (target only)

Interchangeability asks, for each matched pair: can the old part be fitted in place of the new one
in the new assembly? *yes* when the geometry is identical; *no* when something it mates through
changed (a fit diameter, a joint hole, a bolt pattern, or what it mates with) — the breaking
interface is named; *needs review* when the part changed but every measured interface is the same.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

SIG_REL = 0.01
SHAPE_REL = 0.15


def _norm(name: str) -> str:
    s = re.sub(r"(_|-|\s)(body|solid)\d+$", "", name.lower())
    return re.sub(r"[\s_\-./]+", "", s)


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-9)


def _dims(p) -> list[float]:
    return sorted(b - a for a, b in zip(p.bbox.min, p.bbox.max))


def _same_signature(a, b, rel=SIG_REL) -> bool:
    return (_close(a.volume, b.volume, rel) and _close(a.area, b.area, rel)
            and all(_close(x, y, rel) or abs(x - y) < 0.02 for x, y in zip(_dims(a), _dims(b))))


def _similarity(a, b) -> float:
    """1.0 for identical volume and envelope, falling with the worst relative difference."""
    diffs = [abs(a.volume - b.volume) / max(a.volume, b.volume, 1e-9)]
    diffs += [abs(x - y) / max(x, y, 1e-9) for x, y in zip(_dims(a), _dims(b))]
    return max(0.0, 1.0 - max(diffs))


def _holes(graph, pid) -> Counter:
    return Counter(round(f["diameter"], 2) for f in graph.features if f["part_id"] == pid and f["kind"] == "hole")


def _layout(graph, pid) -> list[tuple]:
    """Hole layout that survives a change of part frame: every pair of holes as (diameters, distance).

    Parallel holes are measured axis to axis, so a hole made deeper (its mid-depth centre moves along
    its axis) is not mistaken for a hole that moved.
    """
    import numpy as np

    holes = [f for f in graph.features if f["part_id"] == pid and f["kind"] == "hole"][:80]
    out = []
    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            a, b = holes[i], holes[j]
            ca, cb, ax = np.asarray(a["center"], float), np.asarray(b["center"], float), np.asarray(a["axis"], float)
            d = cb - ca
            if abs(abs(float(np.dot(ax, b["axis"]))) - 1) < 1e-3:
                dist = float(np.linalg.norm(d - ax * np.dot(d, ax)))
            else:
                dist = float(np.linalg.norm(d))
            out.append((tuple(sorted((round(a["diameter"], 2), round(b["diameter"], 2)))), dist))
    return sorted(out)


def _same_layout(la: list, lb: list, tol: float = 0.05) -> bool:
    if len(la) != len(lb):
        return False
    pool = defaultdict(list)
    for key, d in lb:
        pool[key].append(d)
    for key, d in la:
        cands = pool.get(key)
        if not cands:
            return False
        k = min(range(len(cands)), key=lambda i: abs(cands[i] - d))
        if abs(cands[k] - d) > tol:
            return False
        cands.pop(k)
    return True


def _depths(graph, pid) -> Counter:
    return Counter((round(f["diameter"], 2), round(f["depth"], 1)) for f in graph.features
                   if f["part_id"] == pid and f["kind"] == "hole")


def _patterns(graph, pid) -> Counter:
    out = Counter()
    for f in graph.features:
        if f["part_id"] == pid and f["kind"] == "pattern" and f["pattern"] != "group":
            size = round(f["pcd"], 2) if f["pattern"] == "circle" else tuple(sorted([round(f["a"], 2), round(f["b"], 2)]))
            out[(f["pattern"], f["count"], round(f["diameter"], 2), size)] += 1
    return out


def match_parts(base, target) -> list[dict]:
    """Pairs (base part id, target part id, method, similarity) plus unmatched on either side."""
    pairs: list[dict] = []
    left_b = {p.id: p for p in base.parts}
    left_t = {p.id: p for p in target.parts}

    def take(b, t, method, sim):
        pairs.append({"base": b.id, "target": t.id, "method": method, "similarity": round(sim, 3)})
        left_b.pop(b.id)
        left_t.pop(t.id)

    by_name: dict[str, list] = defaultdict(list)
    for t in target.parts:
        by_name[_norm(t.name)].append(t)
    for b in list(left_b.values()):
        cands = [t for t in by_name.get(_norm(b.name), []) if t.id in left_t]
        if len(cands) == 1 and _similarity(b, cands[0]) > 0.3:
            take(b, cands[0], "name", _similarity(b, cands[0]))
    for b in list(left_b.values()):
        cands = [t for t in left_t.values() if _same_signature(b, t)]
        if cands:
            t = max(cands, key=lambda t: _similarity(b, t))
            take(b, t, "signature", _similarity(b, t))
    # changed parts: similar shape, best by a clear margin both ways
    scored = []
    for b in left_b.values():
        for t in left_t.values():
            if _close(b.volume, t.volume, SHAPE_REL) and all(_close(x, y, SHAPE_REL) for x, y in zip(_dims(b), _dims(t))):
                scored.append((_similarity(b, t), b.id, t.id))
    scored.sort(reverse=True)
    for sim, bid, tid in scored:
        if bid not in left_b or tid not in left_t:
            continue
        # accept only a mutual best match that beats every alternative for either part by a clear margin
        alt = [s2 for s2, b2, t2 in scored
               if (b2 in left_b and t2 in left_t) and ((b2 == bid) ^ (t2 == tid))]
        if alt and sim - max(alt) < 0.05:
            continue
        take(left_b[bid], left_t[tid], "shape", sim)
    for b in left_b.values():
        pairs.append({"base": b.id, "target": None, "method": None, "similarity": None})
    for t in left_t.values():
        pairs.append({"base": None, "target": t.id, "method": None, "similarity": None})
    return pairs


def _counts(graph) -> Counter:
    return Counter(i.part_id for i in graph.instances)


def _interface(graph, pid) -> dict:
    """What a part mates through: fit and joint-hole diameters, patterns on its joints, and its partners."""
    insts = {i.id for i in graph.instances if i.part_id == pid}
    part_of = {i.id: i.part_id for i in graph.instances}
    fits, joints, partners = Counter(), Counter(), set()
    for c in graph.contacts:
        if c["a"] not in insts and c["b"] not in insts:
            continue
        mine = "a" if c["a"] in insts else "b"
        other = c["b"] if mine == "a" else c["a"]
        partners.add(part_of[other])
        for f in c.get("fits", []):
            d = f["shaft_diameter"] if f["shaft_on"] == mine else f["hole_diameter"]
            fits[round(d, 2)] += 1
        for j in c.get("joints", []):
            if j["hole_on"] == mine:
                joints[round(j["diameter"], 2)] += 1
            elif j.get("partner_diameter") is not None:
                joints[round(j["partner_diameter"], 2)] += 1
    return {"fits": fits, "joints": joints, "partners": partners}


def _fmt(c: Counter) -> str:
    return ", ".join(f"{n}× Ø{d:g}" for d, n in sorted(c.items())) or "none"


def compare(base, target) -> dict:
    pairs = match_parts(base, target)
    bp = {p.id: p for p in base.parts}
    tp = {p.id: p for p in target.parts}
    bc, tc = _counts(base), _counts(target)
    t_of = {pr["base"]: pr["target"] for pr in pairs if pr["base"] and pr["target"]}

    changes = []
    for pr in pairs:
        b = bp.get(pr["base"]) if pr["base"] else None
        t = tp.get(pr["target"]) if pr["target"] else None
        rec = {"base": pr["base"], "target": pr["target"], "base_name": b.name if b else None, "target_name": t.name if t else None,
               "method": pr["method"], "similarity": pr["similarity"], "kinds": [], "details": []}
        if b and not t:
            rec["status"] = "removed"
            rec["details"].append(f"{bc[b.id]} in base, none in target")
            rec["details"].append("envelope " + " × ".join(f"{x:.1f}" for x in _dims(b)) + f" mm, {b.volume / 1000:.2f} cm³")
        elif t and not b:
            rec["status"] = "added"
            rec["details"].append(f"{tc[t.id]} in target")
            rec["details"].append("envelope " + " × ".join(f"{x:.1f}" for x in _dims(t)) + f" mm, {t.volume / 1000:.2f} cm³")
        else:
            # 1e-3: a re-export moves B-rep properties by float noise, not by design
            identical = (_same_signature(b, t, 1e-3) and _holes(base, b.id) == _holes(target, t.id)
                         and _same_layout(_layout(base, b.id), _layout(target, t.id))
                         and _depths(base, b.id) == _depths(target, t.id) and _patterns(base, b.id) == _patterns(target, t.id))
            if not identical:
                rec["kinds"].append("geometry")
                dv = (t.volume - b.volume) / max(b.volume, 1e-9) * 100
                db, dt = _dims(b), _dims(t)
                if any(abs(x - y) > 0.02 for x, y in zip(db, dt)):
                    rec["kinds"].append("resized")
                    rec["details"].append("envelope " + " × ".join(f"{x:.1f}" for x in db) + " → " + " × ".join(f"{y:.1f}" for y in dt) + " mm")
                if abs(dv) > 0.01:
                    rec["details"].append(f"volume {dv:+.1f} %")
                hb, ht = _holes(base, b.id), _holes(target, t.id)
                if hb != ht:
                    rec["kinds"].append("holes")
                    added, removed = ht - hb, hb - ht
                    if added:
                        rec["details"].append("holes added: " + _fmt(added))
                    if removed:
                        rec["details"].append("holes removed: " + _fmt(removed))
                elif not _same_layout(_layout(base, b.id), _layout(target, t.id)):
                    rec["kinds"].append("holes")
                    rec["details"].append("holes moved (same diameters, different spacing)")
                elif _depths(base, b.id) != _depths(target, t.id):
                    rec["kinds"].append("holes")
                    db_, dt_ = _depths(base, b.id) - _depths(target, t.id), _depths(target, t.id) - _depths(base, b.id)
                    rec["details"].append("hole depth " + ", ".join(f"Ø{k[0]:g} ↧{k[1]:g}" for k in sorted(db_)) + " → "
                                          + ", ".join(f"Ø{k[0]:g} ↧{k[1]:g}" for k in sorted(dt_)))
                pb_, pt_ = _patterns(base, b.id), _patterns(target, t.id)
                if pb_ != pt_:
                    rec["kinds"].append("pattern")
                    gone, new = pb_ - pt_, pt_ - pb_
                    desc = lambda k: f"{k[1]}× Ø{k[2]:g} " + (f"on PCD {k[3]:g}" if k[0] == "circle" else f"on {k[3][0]:g} × {k[3][1]:g}")
                    rec["details"].append("bolt pattern " + (", ".join(desc(k) for k in gone) or "—") + " → "
                                          + (", ".join(desc(k) for k in new) or "—"))
            if b.material and t.material and b.material != t.material:      # unknown on one side is not a change
                rec["kinds"].append("material")
                rec["details"].append(f"material {b.material or '—'} → {t.material or '—'}")
            if bc[b.id] != tc[t.id]:
                rec["kinds"].append("quantity")
                rec["details"].append(f"quantity {bc[b.id]} → {tc[t.id]}")
            if b.name != t.name and pr["method"] != "name":
                rec["kinds"].append("renamed")
            rec["status"] = "modified" if any(k in rec["kinds"] for k in ("geometry", "material")) else (
                "unchanged" if not rec["kinds"] or rec["kinds"] == ["renamed"] else "modified")
        changes.append(rec)

    # interchangeability: can the base part replace the target part in the target assembly?
    matrix = []
    for rec in changes:
        if rec["status"] in ("added", "removed"):
            continue
        b, t = bp[rec["base"]], tp[rec["target"]]
        if "geometry" not in rec["kinds"]:
            matrix.append({"base": b.id, "target": t.id, "name": t.name, "verdict": "yes", "reason": "identical geometry"})
            continue
        ib, it = _interface(base, b.id), _interface(target, t.id)
        mapped = {t_of.get(x) for x in ib["partners"]}
        breaks, recount = [], []
        # a new or lost mating diameter breaks the part's interface; the same diameters used a different
        # number of times only means the assembly around it changed
        for what, x, y in (("fits", ib["fits"], it["fits"]), ("joint holes", ib["joints"], it["joints"])):
            if set(x) != set(y):
                breaks.append(f"{what} {_fmt(x)} → {_fmt(y)}")
            elif x != y:
                recount.append(f"{what} used {_fmt(x)} → {_fmt(y)}")
        if _patterns(base, b.id) != _patterns(target, t.id):
            breaks.append("bolt pattern changed")
        lost = [tp[x].name for x in it["partners"] if x not in mapped and x in tp]
        if breaks:
            matrix.append({"base": b.id, "target": t.id, "name": t.name, "verdict": "no", "reason": "; ".join(breaks)})
        elif lost or recount:
            why = []
            if lost:
                why.append("now mates with " + ", ".join(sorted(lost)[:4]))
            why += recount
            matrix.append({"base": b.id, "target": t.id, "name": t.name, "verdict": "needs review",
                           "reason": "its own mating diameters are unchanged, but " + "; ".join(why) + " — check those interfaces"})
        else:
            matrix.append({"base": b.id, "target": t.id, "name": t.name, "verdict": "needs review",
                           "reason": "the part changed but every measured interface is the same: " + "; ".join(rec["details"][:2])})

    summary = Counter(r["status"] for r in changes)
    verdicts = Counter(m["verdict"] for m in matrix)
    return {"changes": changes, "interchangeability": matrix,
            "summary": {"unchanged": summary["unchanged"], "modified": summary["modified"], "added": summary["added"],
                        "removed": summary["removed"], "yes": verdicts["yes"], "no": verdicts["no"],
                        "needs_review": verdicts["needs review"]},
            "pairs": pairs}


def finding_key(f: dict, part_map: dict[str, str], inst_part: dict[str, str]) -> str:
    """A revision-independent key: the check and the (mapped) parts it is about."""
    parts = set()
    for e in f["evidence"]:
        if e.get("type") == "part" and e.get("id"):
            parts.add(part_map.get(e["id"], e["id"]))
        elif e.get("type") == "instance" and e.get("id") in inst_part:
            pid = inst_part[e["id"]]
            parts.add(part_map.get(pid, pid))
    return f"{f['check_id']}|{f['title']}|{','.join(sorted(parts))}"


def findings_delta(base_findings: list[dict], target_findings: list[dict], base, target, pairs) -> dict:
    part_map = {pr["base"]: pr["target"] for pr in pairs if pr["base"] and pr["target"]}
    b_inst = {i.id: i.part_id for i in base.instances}
    t_inst = {i.id: i.part_id for i in target.instances}
    bk = {finding_key(f, part_map, b_inst): f for f in base_findings}
    tk = {finding_key(f, {}, t_inst): f for f in target_findings}
    return {
        "new": [tk[k] for k in tk if k not in bk],
        "fixed": [bk[k] for k in bk if k not in tk],
        "unchanged": [tk[k] for k in tk if k in bk],
    }
