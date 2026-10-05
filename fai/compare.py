"""Revision compare: which characteristics were added, removed or changed.

Characteristics are matched by what they are (type, nominal, feature count),
not by balloon number — a new callout renumbers everything after it. A
matched pair whose limits, callout text or thread depth differ is "changed".
"""
from __future__ import annotations


def _key(c: dict) -> tuple:
    if c["kind"] == "gdt":
        # every frame has nominal 0: identify it by its zone and callout instead
        return (c["kind"], c["type"], c.get("upper"), c["designator"])
    return (c["kind"], c["type"], None if c.get("nominal") is None else round(c["nominal"], 4), c.get("count", 1))


def _same(a: dict, b: dict) -> bool:
    return ((a.get("lower"), a.get("upper"), a["requirement"], a["designator"])
            == (b.get("lower"), b.get("upper"), b["requirement"], b["designator"]))


def compare(old: list[dict], new: list[dict]) -> dict:
    left = list(old)
    rows = []
    for n in new:
        cands = [o for o in left if _key(o) == _key(n)]
        if not cands and n["kind"] in ("note", "thread"):
            cands = [o for o in left if o["kind"] == n["kind"] and o["designator"].split()[0] == n["designator"].split()[0]]
        if not cands and n["kind"] == "gdt":
            # same frame, one cell edited (a datum letter, a modifier): same zone, nearest balloon
            cands = [o for o in left if o["kind"] == "gdt" and o.get("upper") == n.get("upper")
                     and o["page"] == n["page"]]
            cands = sorted(cands, key=lambda o: abs(o["no"] - n["no"]))[:1]
        if not cands and n["kind"] == "dimension" and n.get("nominal") is not None:
            # same kind of size, nominal moved: changed, not removed + added
            cands = [o for o in left if o["kind"] == "dimension" and o["type"] == n["type"] and o.get("nominal")
                     and abs(o["nominal"] - n["nominal"]) <= max(0.5, 0.02 * n["nominal"])
                     and o.get("count", 1) == n.get("count", 1)]
        if cands:
            o = min(cands, key=lambda o: (not _same(o, n), abs(o["no"] - n["no"])))
            left.remove(o)
            rows.append({"status": "same" if _same(o, n) else "changed", "old": o, "new": n,
                         "what": _what(o, n)})
        else:
            rows.append({"status": "added", "old": None, "new": n, "what": "new characteristic"})
    for o in left:
        rows.append({"status": "removed", "old": o, "new": None, "what": "no longer on the drawing"})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("same", "changed", "added", "removed")}
    return {"rows": rows, "counts": counts}


def _what(o: dict, n: dict) -> str:
    if _same(o, n):
        return ""
    parts = []
    if o.get("nominal") != n.get("nominal"):
        parts.append(f"nominal {o.get('nominal')} → {n.get('nominal')}")
    if (o.get("lower"), o.get("upper")) != (n.get("lower"), n.get("upper")):
        parts.append(f"limits {o.get('lower')}–{o.get('upper')} → {n.get('lower')}–{n.get('upper')}")
    if not parts and o["requirement"] != n["requirement"]:
        parts.append(f"requirement “{o['requirement']}” → “{n['requirement']}”")
    if o["designator"] != n["designator"]:
        parts.append(f"callout “{o['designator']}” → “{n['designator']}”"
                     + ("" if parts else ", limits unchanged"))
    return "; ".join(parts)
