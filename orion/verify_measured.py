"""Convert measured_only records to tier1_exact where the math already exists.

The 632 measured_only records split 600 / 32: the 600 gNucleus variants have
circle/line/arc profiles and only Pad/Pocket/Revolution/Groove features, which
the graph-analytic verifier (orion/verify_masters, 229/229 on the masters)
proves exactly. They are unverified only because import stored the accepted
body volume, never the per-feature AddSubShape.

This module rebuilds each such record in FreeCAD, measures the tool solids,
re-derives each feature volume from the sketch geometry, and upgrades the
record to tier1_exact when every feature matches to REL_TOL. B-spline and
loft records are left measured_only — they are the genuine verification gap.

Writes to the WORKING db (corpus_v2.db), never the frozen baseline.

Usage:
    python -m orion.verify_measured --db data/forge/corpus_v2.db --limit 50
    python -m orion.verify_measured --db data/forge/corpus_v2.db           # all
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3

from . import corpus_db, tier1
from .forge import build_and_measure, workdir
from .verify_masters import REL_TOL, _axis_2d

CLOSED = {"Pad", "Pocket", "Revolution", "Groove"}


def _sketch_z(sk: dict) -> float:
    gp = sk.get("global_placement")
    if gp and gp.get("pos"):
        return float(gp["pos"][2])
    return float(sk.get("z") or 0.0)


def _circle_loft(graph: dict, feat: dict):
    """If a Loft is circle-to-circle between parallel planes, return
    (r1, r2, h) for the prismatoid; else None (not closed-form)."""
    sk = {s["id"]: s for s in graph.get("sketches", [])}
    sects = [d["source"] for d in graph.get("dependencies", [])
             if d["target"] == feat["id"] and d["kind"] in ("profile", "section")]
    if len(sects) != 2:
        return None
    circ = []
    for sid in sects:
        s = sk.get(sid)
        live = [e for e in (s or {}).get("geometry", [])
                if not e.get("construction")]
        if len(live) != 1 or live[0].get("type") != "Circle":
            return None
        circ.append((float(live[0]["radius"]), _sketch_z(s)))
    (r1, z1), (r2, z2) = circ
    return r1, r2, abs(z2 - z1)


def _reachable(graph: dict) -> bool:
    """True when every solid feature is closed-form and no sketch carries a
    curve the analytic area cannot integrate."""
    for f in graph.get("features", []):
        t = f.get("type")
        if t in ("Body", "Sketch"):
            continue
        if t == "Loft":
            if _circle_loft(graph, f) is None:
                return False
            continue
        if t not in CLOSED:
            return False
    for sk in graph.get("sketches", []):
        for e in sk.get("geometry", []):
            t = e.get("type")
            if t not in ("Circle", "LineSegment", "ArcOfCircle", "BSpline"):
                return False
            if t == "BSpline" and e.get("rational"):
                return False
    return True


def _verify(graph: dict, measured: dict) -> tuple[bool, list[dict]]:
    """Per-feature closed-form vs measured AddSubShape. Returns
    (all_passed, rows). Same logic as verify_masters, applied per record."""
    if not measured or measured.get("error"):
        return False, []
    by_name = {f["name"]: f for f in measured.get("features", [])}
    sketches = {s["id"]: s for s in graph.get("sketches", [])}
    profile_of = {d["target"]: d["source"] for d in graph.get("dependencies", [])
                  if d.get("kind") == "profile"}
    rows, ok = [], True
    checked = 0
    for f in graph.get("features", []):
        ftype, fid = f.get("type"), f.get("id")
        if ftype == "Loft":
            cl = _circle_loft(graph, f)
            meas = (by_name.get(fid) or {}).get("addsub_volume")
            if cl is None or not meas:
                return False, rows
            r1, r2, h = cl
            a1, a2 = math.pi * r1 * r1, math.pi * r2 * r2
            am = math.pi * ((r1 + r2) / 2) ** 2
            pred, why = tier1.prismatoid_volume(a1, am, a2, h)
            if pred is None:
                return False, rows
            err = abs(pred - meas) / meas
            ok = ok and err <= REL_TOL
            checked += 1
            rows.append({"feature": fid, "type": "Loft",
                         "predicted": round(pred, 6), "measured": round(meas, 6),
                         "rel_err": err, "passed": err <= REL_TOL})
            continue
        if ftype not in CLOSED:
            continue
        meas = (by_name.get(fid) or {}).get("addsub_volume")
        sk = sketches.get(profile_of.get(fid))
        if not meas or sk is None:
            return False, rows
        area, centroid, why = tier1.sketch_area(
            sk.get("geometry", []), sk.get("external_geometry", []))
        if area is None:
            return False, rows
        params = f.get("parameters") or {}
        if ftype in ("Pad", "Pocket"):
            pred, why = tier1.extrusion_volume(area, params)
        else:
            axis = _axis_2d(sk.get("plane", "XY"), params.get("_ReferenceAxis"))
            gp = sk.get("global_placement")
            if axis is None or (gp and any(abs(v) > 1e-9
                                           for v in (gp.get("pos") or [0, 0, 0]))):
                return False, rows
            pred, why = tier1.revolution_volume(area, centroid, axis, params)
        if pred is None:
            return False, rows
        err = abs(pred - meas) / meas
        ok = ok and err <= REL_TOL
        checked += 1
        rows.append({"feature": fid, "type": ftype,
                     "predicted": round(pred, 6), "measured": round(meas, 6),
                     "rel_err": err, "passed": err <= REL_TOL})
    return (ok and checked > 0), rows


def run(db_path: str, limit: int = 0) -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(corpus_db.SCHEMA)
    rows = con.execute(
        "SELECT blueprint_hash, status, payload FROM records "
        "WHERE status IN ('real', 'real_variant')").fetchall()
    wd = workdir()
    stats = {"scanned": 0, "reachable": 0, "converted": 0,
             "failed_match": 0, "build_failed": 0, "skipped_hard": 0}
    n = 0
    for bh, status, payload in rows:
        p = json.loads(payload)
        if (p.get("verification") or {}).get("status") == "tier1_exact":
            continue
        stats["scanned"] += 1
        graph = p.get("feature_graph", {})
        if not _reachable(graph):
            stats["skipped_hard"] += 1
            continue
        stats["reachable"] += 1
        if limit and n >= limit:
            continue
        n += 1
        _log, measured = build_and_measure(graph, wd, f"vm_{bh[:10]}")
        if not measured:
            stats["build_failed"] += 1
            continue
        passed, vrows = _verify(graph, measured)
        if not passed:
            stats["failed_match"] += 1
            continue
        # Upgrade: attach the per-feature proof and mark tier1_exact.
        p["verification"] = {
            "status": "tier1_exact", "checked": len(vrows), "skipped": 0,
            "max_rel_err": max((r["rel_err"] for r in vrows), default=0.0),
            "rows": vrows, "method": "rebuilt+graph_analytic"}
        p["verdict"]["passed"] = True
        p["verdict"]["assertions"] = [
            {"id": f"tool_{r['feature']}", "kind": "feature_volume",
             "feature": r["feature"], "tier": 1, "tol_rel": REL_TOL,
             "target": r["predicted"], "measured": r["measured"],
             "rel_err": r["rel_err"], "passed": True} for r in vrows]
        corpus_db.insert(con, p, status)
        stats["converted"] += 1
        if stats["converted"] % 25 == 0:
            con.commit()
    con.commit()
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    print(json.dumps(run(args.db, args.limit), indent=1))


if __name__ == "__main__":
    main()
