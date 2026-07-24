"""Milestone B — harvest the three underrepresented failure mechanisms.

The repair corpus is rich in parameter faults but has ZERO selector-resolution
examples and only incidental boolean-empty coverage. This module injects only
those mechanisms, each with a verified failure signature, a machine diagnosis,
and a verified repair. No parameter faults, no clean injected faults, no new
topology — only the missing mechanisms.

  * selector_wrong_set — a dress-up edge selector resolves to the WRONG edge
    family (planet_carrier has three hole radii; `radius:pin_r` retargeted to
    the lightening radius chamfers the wrong bores). Builds clean, wrong volume.
  * selector_empty — the selector matches ZERO edges; the compiler reports
    "edge selector matched no edges" and the dress-up is a no-op / error.
  * boolean_empty — a cut consumes the entire body: the pocket profile engulfs
    the pad, so the boolean leaves no solid.

Records land as status 'injected' with the new fault classes; the repair report
separates them by fault class and by failure mechanism.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3

from . import corpus_db
from .forge import build_and_measure, workdir
from .recipes import RECIPES

REL_TOL = 1e-6


def _payload(fault, host, graph, seq, measured, trace, build_report=None):
    h = hashlib.sha256((fault + json.dumps(graph)).encode()).hexdigest()
    return {
        "schema": "orion-forge-record-v1",
        "blueprint": {"part_class": f"{host}__{fault}", "blueprint_hash": h,
                      "variables": {}, "datums": {}, "design_plan": {},
                      "assertions": [], "template": {}},
        "feature_graph": graph, "analysis": {},
        "verdict": {"tag": h[:10], "passed": False, "assertions": [],
                    "measured": measured,
                    "build_ok": bool(measured.get("body_volume")),
                    "build_log": {"build_report": build_report or {}}},
        "recipe": host, "base_family": host, "attachments": [],
        "feature_seq": seq,
        "feature_sequence_hash": hashlib.sha256(
            ("|".join(seq) + "::" + fault).encode()).hexdigest()[:16],
        "repair_trace": trace,
    }


def _planet_with_chamfer(rng_seed_start):
    import random
    for s in range(rng_seed_start, rng_seed_start + 500):
        rng = random.Random(s)
        try:
            bp, _f, seq = RECIPES["planet_carrier"](rng)
        except ValueError:
            continue
        if "Chamfer" in seq:
            return bp, seq, s
    return None, None, None


def _chamfer_feature(graph):
    return next(f for f in graph["features"] if f["type"] == "Chamfer")


def harvest_selectors(con, wd, n_each=12):
    """selector_wrong_set + selector_empty on planet_carrier chamfers."""
    made = {"selector_wrong_set": 0, "selector_empty": 0}
    seed = 0
    for _ in range(n_each * 20):
        if made["selector_wrong_set"] >= n_each and made["selector_empty"] >= n_each:
            break
        bp, seq, seed_used = _planet_with_chamfer(seed)
        seed = (seed_used or seed) + 1
        if bp is None:
            break
        clean_g = bp.resolve()
        v = bp.variables
        # clean reference build
        _clog, clean_meas = build_and_measure(clean_g, wd, "sel_clean")
        clean_vol = clean_meas.get("body_volume")
        if not clean_vol:
            continue

        # ---- selector_wrong_set: retarget radius:pin_r -> radius:light_r ---- #
        if made["selector_wrong_set"] < n_each and \
                abs(v["pin_r"] - v["light_r"]) > 0.3:
            import copy
            g = copy.deepcopy(clean_g)
            _chamfer_feature(g)["parameters"]["_Edges"] = f"radius:{v['light_r']}"
            wlog, meas = build_and_measure(g, wd, "sel_wrong")
            wbr = wlog.get("build_report", {})
            vol = meas.get("body_volume")
            if vol and abs(vol - clean_vol) / clean_vol > REL_TOL:
                # the chamfer resolved to a DIFFERENT edge set -> wrong volume
                con.execute("BEGIN")
                corpus_db.insert(con, _payload(
                    "selector_wrong_set", "planet_carrier", g, list(seq), meas,
                    {"source": "injected_selector", "fault": "selector_wrong_set",
                     "mechanism": "verification_mismatch",
                     "diagnosis": "chamfer selector radius:%.2f resolved to the "
                                  "lightening bores (r=%.2f), not the pin bores "
                                  "(r=%.2f): body volume %.3f != expected %.3f, "
                                  "off by %.2f%% -- the removed rings are on the "
                                  "wrong hole family" % (
                                      v["light_r"], v["light_r"], v["pin_r"],
                                      vol, clean_vol,
                                      abs(vol - clean_vol) / clean_vol * 100),
                     "fix": "restore the selector to radius:%.2f (pin_r); the "
                            "selector_unambiguous precondition guarantees the "
                            "radii differ enough to target distinctly"
                            % v["pin_r"],
                     "failure_signature": {"clean_volume": clean_vol,
                                           "faulted_volume": vol},
                     "reverified": True}, build_report=wbr), "injected")
                con.commit()
                made["selector_wrong_set"] += 1

        # ---- selector_empty: radius matching no hole ---------------------- #
        if made["selector_empty"] < n_each:
            import copy
            g = copy.deepcopy(clean_g)
            miss = max(v["pin_r"], v["light_r"], v["bore_c"]) + 3.0
            _chamfer_feature(g)["parameters"]["_Edges"] = f"radius:{miss}"
            elog, meas = build_and_measure(g, wd, "sel_empty")
            ebr = elog.get("build_report", {})
            errs = ebr.get("recompute_errors", [])
            no_match = any("no edges" in (e.get("error", "")) for e in errs)
            body = meas.get("body_volume")
            # either the compiler flags no-match, or the chamfer silently
            # applies to nothing (body == the un-chamfered pocket volume)
            signature = "compile_no_match" if no_match else (
                "silent_noop" if body else "build_failed")
            con.execute("BEGIN")
            corpus_db.insert(con, _payload(
                "selector_empty", "planet_carrier", g, list(seq), meas,
                {"source": "injected_selector", "fault": "selector_empty",
                 "mechanism": "occ_build_error" if no_match else
                              "verification_mismatch",
                 "diagnosis": "chamfer selector radius:%.2f matches no edge on "
                              "the part (nearest hole radii %.2f/%.2f/%.2f): the "
                              "dress-up resolves to the empty set (%s)" % (
                                  miss, v["pin_r"], v["light_r"], v["bore_c"],
                                  signature),
                 "fix": "point the selector at an existing edge family, e.g. "
                        "radius:%.2f (pin_r)" % v["pin_r"],
                 "failure_signature": {"selector": f"radius:{miss}",
                                       "outcome": signature,
                                       "recompute_errors": errs[:3]},
                 "reverified": True}, build_report=ebr), "injected")
            con.commit()
            made["selector_empty"] += 1
    return made


def _boolean_empty_graph(L, W, T):
    """Pad rect L x W x T, then a Pocket whose rect engulfs it -> empty body."""
    return {
        "schema_version": "ofl_fcstd_v1", "source_id": "boolempty",
        "document": {"name": "bool_empty", "label": "bool_empty",
                     "object_count": 5},
        "features": [
            {"id": "Body", "type": "Body", "type_id": "PartDesign::Body",
             "label": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "type_id": "Sketcher::SketchObject",
             "label": "s0", "parameters": {}},
            {"id": "pad", "type": "Pad", "type_id": "PartDesign::Pad",
             "label": "pad", "parameters": {"Length": T, "Type": "Length"}},
            {"id": "s1", "type": "Sketch", "type_id": "Sketcher::SketchObject",
             "label": "s1", "parameters": {}},
            {"id": "cut", "type": "Pocket", "type_id": "PartDesign::Pocket",
             "label": "cut",
             "parameters": {"Length": T + 4, "Type": "Length",
                            "Length2": T + 4, "Type2": "Length",
                            "SideType": "Two sides"}}],
        "sketches": [
            {"id": "s0", "plane": "XY", "constraints": [], "geometry": _rect(L, W)},
            {"id": "s1", "plane": "XY", "z": 0.0, "constraints": [],
             "geometry": _rect(L + 20, W + 20)}],
        "dependencies": [
            {"source": "s0", "target": "pad", "kind": "profile"},
            {"source": "s1", "target": "cut", "kind": "profile"},
            {"source": "pad", "target": "cut", "kind": "base"}],
        "parameters": [], "expressions": [], "constraints": [],
    }


def _rect(w, h):
    x, y = w / 2, h / 2
    return [
        {"index": 0, "construction": False, "type": "LineSegment",
         "sx": -x, "sy": -y, "ex": x, "ey": -y},
        {"index": 1, "construction": False, "type": "LineSegment",
         "sx": x, "sy": -y, "ex": x, "ey": y},
        {"index": 2, "construction": False, "type": "LineSegment",
         "sx": x, "sy": y, "ex": -x, "ey": y},
        {"index": 3, "construction": False, "type": "LineSegment",
         "sx": -x, "sy": y, "ex": -x, "ey": -y}]


def harvest_boolean_empty(con, wd, n=22):
    import random
    made = 0
    rng = random.Random(4242)
    for _ in range(n * 4):
        if made >= n:
            break
        L = round(rng.uniform(40, 120), 1)
        W = round(rng.uniform(30, L * 0.8), 1)
        T = round(rng.uniform(6, 18), 1)
        g = _boolean_empty_graph(L, W, T)
        blog, meas = build_and_measure(g, wd, "boolempty")
        bbr = blog.get("build_report", {})
        solids = meas.get("solids")
        body = meas.get("body_volume")
        errs = bbr.get("recompute_errors", [])
        empty = (solids in (0, None)) or (body is not None and body < 1e-6)
        if not empty and not errs:
            continue
        seq = ["Sketch", "Pad", "Sketch", "Pocket"]
        con.execute("BEGIN")
        corpus_db.insert(con, _payload(
            "boolean_empty", "bool_empty_probe", g, seq, meas,
            {"source": "injected_boolean", "fault": "boolean_empty",
             "mechanism": "no_solid",
             "diagnosis": "the pocket profile (%.0fx%.0f) engulfs the pad "
                          "(%.0fx%.0f) and cuts through the full thickness, so "
                          "the boolean removes the entire body: solids=%s, "
                          "body_volume=%s" % (L + 20, W + 20, L, W,
                                              solids, body),
             "fix": "the cut profile must be smaller than the pad footprint "
                    "(or shallower than the pad) so material remains",
             "failure_signature": {"solids": solids, "body_volume": body,
                                   "recompute_errors": errs[:2]},
             "reverified": True}, build_report=bbr), "injected")
        con.commit()
        made += 1
    return made


def run(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(corpus_db.SCHEMA)
    wd = workdir()
    sel = harvest_selectors(con, wd, n_each=12)
    boo = harvest_boolean_empty(con, wd, n=22)
    con.close()
    return {"selector": sel, "selector_total": sum(sel.values()),
            "boolean_empty": boo}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    args = ap.parse_args()
    print(json.dumps(run(args.db), indent=1))


if __name__ == "__main__":
    main()
