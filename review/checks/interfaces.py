"""D2 Interfaces & fasteners: do mating parts actually bolt together?

Everything here reads measurements the geometry stage made (contacts, the
hole pairs across each joint, features) — no geometry is computed in a check.
Hole and fastener sizes are compared as nominal metric sizes: STEP carries no
thread or fit class.
"""
from __future__ import annotations

import numpy as np

from .base import CheckConfig, Evidence, Finding, Quantity, check

PATTERN_TOL = 0.1          # mm
SEARCH = 3.0               # mm
NOMINAL = "STEP carries no thread or fit class; nominal sizes compared"


def _names(graph) -> dict[str, str]:
    return {i.id: i.name for i in graph.instances}


def _pair_ev(c, names, extra=None) -> list[Evidence]:
    ev = [Evidence(type="instance", id=c["a"], label=names[c["a"]]), Evidence(type="instance", id=c["b"], label=names[c["b"]]),
          Evidence(type="contact", id=c["id"], label=f"{c['type']} contact")]
    return ev + (extra or [])


# ---------------------------------------------------------------- floating --

@check("IF-CONTACT", "1.0.0", "interfaces", "Every part is held by something", requires=["instances"])
def if_contact(graph, cfg: CheckConfig) -> list[Finding]:
    """A part that touches nothing is floating: a missing mate, or a part left where it was modelled."""
    if len(graph.instances) < 2:
        return []
    touched = {c["a"] for c in graph.contacts} | {c["b"] for c in graph.contacts}
    near: dict[str, tuple[float, str]] = {}
    for c in graph.clearances:
        for x, y in ((c["a"], c["b"]), (c["b"], c["a"])):
            if x not in near or c["min_distance"] < near[x][0]:
                near[x] = (c["min_distance"], y)
    names = _names(graph)
    gap = cfg.get("contact_gap_mm")
    out = []
    for i in graph.instances:
        if i.id in touched:
            continue
        if i.id in near:
            d, other = near[i.id]
            stmt = (f"{i.name} touches no other part. The nearest is {names[other]}, {d:.3f} mm away — "
                    f"close enough to be meant as a mate, far enough that nothing holds it.")
            ev = [Evidence(type="instance", id=i.id, label=i.name), Evidence(type="instance", id=other, label=names[other])]
            meas = Quantity(value=round(d, 4), unit="mm", text="gap to nearest part")
        else:
            stmt = f"{i.name} touches no other part and nothing is within 1 mm of it: it floats in the assembly."
            ev = [Evidence(type="instance", id=i.id, label=i.name)]
            meas = Quantity(min=1.0, unit="mm", text="gap to nearest part")
        out.append(Finding(
            check_id="IF-CONTACT", check_version="1.0.0", domain="interfaces", severity="major",
            title="Part is not attached to anything", statement=stmt, measured=meas,
            expected=Quantity(max=gap, unit="mm", basis=cfg.basis("contact_gap_mm")),
            evidence=ev, recommendation="Mate the part in CAD, or remove it if it is left over.", key=f"float:{i.id}"))
    return out


# ------------------------------------------------------------ hole patterns --

def _T(graph, iid) -> np.ndarray:
    return np.asarray(next(i for i in graph.instances if i.id == iid).transform, float)


def _placed_patterns(graph, iid):
    inst = next(i for i in graph.instances if i.id == iid)
    T = np.asarray(inst.transform, float)
    holes = {f["id"]: f for f in graph.features if f["part_id"] == inst.part_id and f["kind"] == "hole"}
    out = []
    for f in graph.features:
        if f["part_id"] != inst.part_id or f["kind"] != "pattern" or f["pattern"] == "group":
            continue
        pts = [T[:3, :3] @ np.asarray(holes[h]["center"]) + T[:3, 3] for h in f["holes"] if h in holes]
        axes = [T[:3, :3] @ np.asarray(holes[h]["axis"]) for h in f["holes"] if h in holes]
        axis = T[:3, :3] @ np.asarray(f["axis"])
        out.append({"f": f, "centroid": T[:3, :3] @ np.asarray(f["centroid"]) + T[:3, 3], "axis": axis / np.linalg.norm(axis),
                    "points": pts, "axes": axes, "depths": [holes[h]["depth"] for h in f["holes"] if h in holes]})
    return out


def _crosses(p, plane) -> bool:
    n = np.asarray(plane["normal"], float)
    if abs(float(np.dot(p["axis"], n))) < 0.9:
        return False
    d = abs(float(np.dot(np.asarray(p["points"][0]) - np.asarray(plane["point"]), n)))
    return d <= max(p["depths"]) / 2 + 0.05 + 1e-6


def pattern_mismatches(graph) -> list[dict]:
    """Paired hole patterns across a joint whose spacing or centre disagree."""
    out = []
    seen = set()
    for c in graph.contacts:
        if not c["planes"]:
            continue
        pa_all, pb_all = _placed_patterns(graph, c["a"]), _placed_patterns(graph, c["b"])
        for plane in c["planes"]:
            n = np.asarray(plane["normal"], float)
            pa = [p for p in pa_all if _crosses(p, plane)]
            pb = [p for p in pb_all if _crosses(p, plane)]
            for x in pa:
                for y in pb:
                    fx, fy = x["f"], y["f"]
                    if fx["pattern"] != fy["pattern"] or fx["count"] != fy["count"]:
                        continue
                    d = x["centroid"] - y["centroid"]
                    lateral = float(np.linalg.norm(d - n * np.dot(d, n)))
                    size = fx["pcd"] if fx["pattern"] == "circle" else float(np.hypot(fx["a"], fx["b"]))
                    if lateral > size / 4:
                        continue
                    # concentric patterns of different sizes are two joints, not one mismatch
                    near = [min(float(np.linalg.norm((py - px) - n * np.dot(py - px, n))) for py in y["points"]) for px in x["points"]]
                    if max(near) > SEARCH:
                        continue
                    if fx["pattern"] == "circle":
                        diff = abs(fx["pcd"] - fy["pcd"])
                    else:
                        diff = abs(fx["a"] - fy["a"]) + abs(fx["b"] - fy["b"])
                    if diff <= PATTERN_TOL and lateral <= PATTERN_TOL:
                        continue
                    key = (c["id"], fx["id"], fy["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"contact": c, "a": fx, "b": fy, "diff": diff, "lateral": lateral,
                                "points": [list(map(float, p)) for p in x["points"] + y["points"]],
                                "holes": list(zip(x["points"] + y["points"], x["axes"] + y["axes"]))})
    return out


@check("IF-PATTERN", "1.0.0", "interfaces", "Bolt patterns match across joints", requires=["contacts", "features"])
def if_pattern(graph, cfg: CheckConfig) -> list[Finding]:
    """Paired hole patterns on mating parts must have the same bolt circle / spacing and centre."""
    names = _names(graph)
    out = []
    for m in pattern_mismatches(graph):
        c, fa, fb = m["contact"], m["a"], m["b"]
        if fa["pattern"] == "circle":
            what = f"bolt circle Ø{fa['pcd']:.2f} vs Ø{fb['pcd']:.2f} mm"
            meas, exp = Quantity(value=fa["pcd"], unit="mm PCD"), Quantity(value=fb["pcd"], unit="mm PCD", basis=f"pattern on {names[c['b']]}")
        else:
            what = f"spacing {fa['a']:.2f} × {fa['b']:.2f} vs {fb['a']:.2f} × {fb['b']:.2f} mm"
            meas = Quantity(value=round(fa["a"] + fa["b"], 4), unit="mm (a+b)", text=f"{fa['a']:.2f} × {fa['b']:.2f}")
            exp = Quantity(value=round(fb["a"] + fb["b"], 4), unit="mm (a+b)", text=f"{fb['a']:.2f} × {fb['b']:.2f}", basis=f"pattern on {names[c['b']]}")
        if m["lateral"] > PATTERN_TOL:
            what += f", centres {m['lateral']:.2f} mm apart"
        out.append(Finding(
            check_id="IF-PATTERN", check_version="1.0.0", domain="interfaces", severity="critical",
            title="Bolt patterns do not match",
            statement=f"The hole pattern on {names[c['a']]} ({fa['description']}) does not line up with the one on "
                      f"{names[c['b']]} ({fb['description']}): {what}. The joint cannot be bolted as drawn.",
            measured=meas, expected=exp,
            evidence=_pair_ev(c, names, [Evidence(type="feature", id=fa["id"], kind="pattern", label=fa["description"]),
                                         Evidence(type="feature", id=fb["id"], kind="pattern", label=fb["description"]),
                                         Evidence(type="measurement", points=m["points"][:2], value=round(m["diff"], 4), unit="mm")]),
            recommendation="Make both parts use one pattern (one dimension drives both, or both from one sketch).",
            key=f"pattern:{c['id']}:{fa['id']}:{fb['id']}"))
    return out


# ------------------------------------------------------------- hole align --

def _on_pattern_hole(point, contact_id, mismatches) -> bool:
    """Is this joint point on the axis of a hole that belongs to a mismatched pattern of the same contact?"""
    q = np.asarray(point, float)
    for m in mismatches:
        if m["contact"]["id"] != contact_id:
            continue
        for c, a in m["holes"]:
            a = np.asarray(a, float) / np.linalg.norm(a)
            d = q - np.asarray(c, float)
            if float(np.linalg.norm(d - a * np.dot(d, a))) < 0.05:
                return True
    return False


@check("IF-HOLE-ALIGN", "1.1.0", "interfaces", "Holes line up across joints", requires=["contacts", "features"])
def if_hole_align(graph, cfg: CheckConfig) -> list[Finding]:
    """A hole crossing a joint must meet a coaxial hole in the mating part, or the fastener cannot pass."""
    tol = cfg.get("hole_align_tol_mm")
    names = _names(graph)
    mismatches = pattern_mismatches(graph)
    out = []
    for c in graph.contacts:
        for j in c.get("joints", []):
            owner = c["a"] if j["hole_on"] == "a" else c["b"]
            other = c["b"] if j["hole_on"] == "a" else c["a"]
            if j["missing"]:
                from .metric import is_clearance_only
                clearance = any(is_clearance_only(d) for d in j.get("stack") or [j["diameter"]])
                # a matched pair is recorded once, from either side: count this part's holes on both sides of it
                sibs = [x for x in c.get("joints", []) if
                        (x["hole_on"] == j["hole_on"] and abs(x["diameter"] - j["diameter"]) < 0.05) or
                        (x["hole_on"] != j["hole_on"] and x["partner_diameter"] is not None
                         and abs(x["partner_diameter"] - j["diameter"]) < 0.05)]
                matched = sum(1 for x in sibs if not x["missing"])
                in_pattern = len(sibs) >= 3 and matched / len(sibs) >= 0.75
                if not clearance and not in_pattern:
                    continue                  # an unused threaded hole covered by the mating part is harmless
                title = ("Clearance hole opens onto solid material" if clearance
                         else "One hole of a matched pattern has no partner")
                why = (f"a fastener through it has nothing to thread into" if clearance else
                       f"{matched} of the {len(sibs)} Ø{j['diameter']:.2f} holes on this joint have partners, this one does not")
                out.append(Finding(
                    check_id="IF-HOLE-ALIGN", check_version="1.1.0", domain="interfaces",
                    severity="critical" if clearance else "major",
                    title=title,
                    statement=f"The Ø{j['diameter']:.2f} hole in {names[owner]} ends against solid material of "
                              f"{names[other]}: there is no hole in {names[other]} within {SEARCH:.0f} mm — {why}.",
                    measured=Quantity(value=j.get("nearest"), unit="mm", text="nearest partner hole" if j.get("nearest") else "no partner hole"),
                    expected=Quantity(max=SEARCH, unit="mm", basis="a partner hole within the search radius"),
                    evidence=_pair_ev(c, names, [Evidence(type="measurement", points=[j["point"]], label="hole exit")]),
                    recommendation=f"Add the matching hole to {names[other]}, or remove the hole from {names[owner]}.",
                    key=f"missing:{c['id']}:{','.join(f'{v:.1f}' for v in j['point'])}"))
                continue
            if j["offset"] is None or j["offset"] <= tol:
                continue
            if _on_pattern_hole(j["point"], c["id"], mismatches):
                continue                      # reported once, as the pattern mismatch it is part of
            sev = "critical" if j["offset"] > min(j["diameter"], j["partner_diameter"]) / 4 else "major"
            out.append(Finding(
                check_id="IF-HOLE-ALIGN", check_version="1.1.0", domain="interfaces", severity=sev,
                title="Holes do not line up",
                statement=f"The Ø{j['diameter']:.2f} hole in {names[owner]} is {j['offset']:.3f} mm off the matching "
                          f"Ø{j['partner_diameter']:.2f} hole in {names[other]}, measured axis to axis at the joint face.",
                measured=Quantity(value=j["offset"], unit="mm", text="axis offset"),
                expected=Quantity(max=tol, unit="mm", basis=cfg.basis("hole_align_tol_mm")),
                evidence=_pair_ev(c, names, [Evidence(type="measurement", points=[j["point"]], value=j["offset"], unit="mm")]),
                recommendation="Locate both holes from the same reference (one sketch, or a shared pattern).",
                key=f"align:{c['id']}:{','.join(f'{v:.1f}' for v in j['point'])}"))
    return out


# ------------------------------------------------------------- fastener size --

def _headed(graph, part_id: str, d: float) -> bool:
    """A shaft is a headed fastener when its part has a coaxial head at least 1.4x its diameter."""
    cyls = [f for f in graph.features if f["part_id"] == part_id and f["kind"] == "cylinder"]
    shaft = next((f for f in cyls if abs(f["diameter"] - d) < 0.05), None)
    if shaft is None:
        return False
    a = np.asarray(shaft["axis"], float)
    for f in cyls:
        if f["diameter"] >= 1.4 * d and abs(abs(float(np.dot(a, f["axis"]))) - 1) < 1e-3:
            off = np.asarray(f["center"], float) - np.asarray(shaft["center"], float)
            if np.linalg.norm(off - a * np.dot(off, a)) < 0.2:
                return True
    return False


def _threaded(graph) -> set[tuple[str, float]]:
    """(instance, shank diameter) pairs that the geometry stage saw threaded into a hole smaller than them."""
    out = set()
    for c in graph.contacts:
        for t in c.get("threads", []):
            out.add((c["a"] if t["shaft_on"] == "a" else c["b"], round(t["shaft_diameter"], 2)))
    return out


def _part(graph, iid: str) -> str:
    return next(i.part_id for i in graph.instances if i.id == iid)


def _fastener_shafts(graph) -> list[dict]:
    """Every fastener shank in the assembly frame: axis line, diameter, metric size.

    A fastener is a headed metric shank that is threaded into something (a tapped hole, an insert, a
    nut) — the thread engagement the geometry stage recorded. A pin has a head-like body too, but it is
    never threaded, so it is not mistaken for a bolt.
    """
    from interface_check.rules import fasteners

    threaded = _threaded(graph)
    out = []
    for inst in graph.instances:
        T = np.asarray(inst.transform, float)
        for f in graph.features:
            if f["part_id"] != inst.part_id or f["kind"] != "cylinder":
                continue
            size = next((s for s, dims in fasteners.METRIC.items() if abs(dims[0] - f["diameter"]) <= 0.05), None)
            if size and _headed(graph, inst.part_id, f["diameter"]) and (inst.id, round(f["diameter"], 2)) in threaded:
                a = T[:3, :3] @ np.asarray(f["axis"], float)
                out.append({"size": size, "point": T[:3, :3] @ np.asarray(f["center"], float) + T[:3, 3],
                            "axis": a / np.linalg.norm(a), "length": f["length"], "inst": inst.id,
                            "diameter": f["diameter"]})
    return out


def _pin_shafts(graph, fast: list[dict]) -> list[dict]:
    """Cylindrical shanks that are not fasteners: dowels, locating pins, shafts."""
    taken = {(s["inst"], round(s["diameter"], 2)) for s in fast}
    out = []
    for inst in graph.instances:
        T = np.asarray(inst.transform, float)
        for f in graph.features:
            if f["part_id"] != inst.part_id or f["kind"] != "cylinder" or f["diameter"] > 12:
                continue
            if (inst.id, round(f["diameter"], 2)) in taken:
                continue
            a = T[:3, :3] @ np.asarray(f["axis"], float)
            out.append({"point": T[:3, :3] @ np.asarray(f["center"], float) + T[:3, 3], "axis": a / np.linalg.norm(a),
                        "length": f["length"], "inst": inst.id, "diameter": f["diameter"]})
    return out


def _stepped_pin(graph, part_id: str, shaft: dict) -> bool:
    """A 'head' as long as or longer than the shank is a stepped pin body, not a screw head."""
    a = np.asarray(shaft["axis"], float)
    for f in graph.features:
        if f["part_id"] == part_id and f["kind"] == "cylinder" and f["diameter"] >= 1.4 * shaft["diameter"]                 and abs(abs(float(np.dot(a, f["axis"]))) - 1) < 1e-3 and f["length"] >= shaft["length"]:
            return True
    return False


def _pin_through(pins: list[dict], j: dict) -> bool:
    """A pin passes through the joint: coaxial with it, and small enough to be inside both holes."""
    p, ax = np.asarray(j["point"], float), np.asarray(j["axis"], float)
    room = min(j["diameter"], j["partner_diameter"] or j["diameter"]) + 0.05
    for s in pins:
        if s["diameter"] > room or abs(float(np.dot(s["axis"], ax))) < 0.999:
            continue
        d = p - s["point"]
        t = float(np.dot(d, s["axis"]))
        if abs(t) <= s["length"] / 2 + 0.5 and float(np.linalg.norm(d - s["axis"] * t)) < 0.1:
            return True
    return False


def _fastener_through(shafts: list[dict], j: dict) -> str | None:
    """Metric size of a modelled fastener whose shank passes through this joint point, if any."""
    p, ax = np.asarray(j["point"], float), np.asarray(j["axis"], float)
    for s in shafts:
        if abs(float(np.dot(s["axis"], ax))) < 0.999:
            continue
        d = p - s["point"]
        t = float(np.dot(d, s["axis"]))
        if abs(t) <= s["length"] / 2 + 0.5 and float(np.linalg.norm(d - s["axis"] * t)) < 0.1:
            return s["size"]
    return None


def _head_contact(graph, shaft_inst: str, d: float) -> str | None:
    """The part clamped under a fastener's head: the contact whose plane sits at the head's underside."""
    inst = next(i for i in graph.instances if i.id == shaft_inst)
    T = np.asarray(inst.transform, float)
    cyls = [f for f in graph.features if f["part_id"] == inst.part_id and f["kind"] == "cylinder"]
    shaft = next((f for f in cyls if abs(f["diameter"] - d) < 0.05), None)
    if shaft is None:
        return None
    a = np.asarray(shaft["axis"], float)
    heads = [f for f in cyls if f["diameter"] >= 1.4 * d and abs(abs(float(np.dot(a, f["axis"]))) - 1) < 1e-3]
    if not heads:
        return None
    head = max(heads, key=lambda f: f["diameter"])
    hc, sc = np.asarray(head["center"], float), np.asarray(shaft["center"], float)
    toward = np.sign(float(np.dot(sc - hc, a))) or 1.0
    under = hc + a * toward * head["length"] / 2            # the head face the shank leaves from
    under_w = T[:3, :3] @ under + T[:3, 3]
    axis_w = T[:3, :3] @ a
    for c in graph.contacts:
        if shaft_inst not in (c["a"], c["b"]):
            continue
        for pl in c["planes"]:
            n = np.asarray(pl["normal"], float)
            if abs(float(np.dot(n, axis_w))) > 0.99 and abs(float(np.dot(np.asarray(pl["point"]) - under_w, n))) < 0.1:
                return c["b"] if c["a"] == shaft_inst else c["a"]
    return None


@check("IF-FASTENER-SIZE", "1.2.0", "interfaces", "Holes and fasteners agree on one size", requires=["contacts", "features"])
def if_fastener_size(graph, cfg: CheckConfig) -> list[Finding]:
    """Mating holes must accept one metric size; the part under a bolt's head needs a clearance hole for it.

    Sizes are ranges (see checks.metric): clearance from just over nominal to ISO 273 coarse, tap drill
    +-0.15, nominal +-0.05. A counterbored hole is judged by every diameter on its axis.
    """
    from interface_check.rules import fasteners
    from . import metric

    names = _names(graph)
    big = cfg.get("max_fastener_hole_mm")
    shafts = _fastener_shafts(graph)
    pins = _pin_shafts(graph, shafts)
    threaded = _threaded(graph)
    out = []
    for c in graph.contacts:
        groups: dict[tuple, list] = {}
        for j in c.get("joints", []):
            if j["missing"] or j["partner_diameter"] is None or j["offset"] is None or j["offset"] > SEARCH:
                continue
            if max(j["diameter"], j["partner_diameter"]) > big:
                continue                      # a bore, not a fastener hole (see max_fastener_hole_mm)
            s1 = j.get("stack") or [j["diameter"]]
            s2 = j.get("partner_stack") or [j["partner_diameter"]]
            if _pin_through(pins, j):
                continue                      # a dowel or locating pin passes here: a pinned joint, not a screwed one
            size = _fastener_through(shafts, j)
            if size:
                from interface_check.rules.fasteners import METRIC
                nominal, tap = METRIC[size][0], METRIC[size][1]
                # a bolt through this joint: each hole on its path must let it pass or be its thread (an insert
                # or a nut may carry the thread further on, so the partner part need not be the tapped one)
                if all(d >= nominal - 0.05 or abs(d - tap) <= metric.TAP_TOL for d in list(s1) + list(s2)):
                    continue
                verdict = ("modelled", size)
            elif any(fasteners.compatible(x, y) for x in s1 for y in s2):
                continue                      # an exact ISO 273 / ISO 2306 match
            elif metric.compatible(s1, s2):
                verdict = ("ambiguous", None)
            else:
                verdict = ("none", None)
            owner = c["a"] if j["hole_on"] == "a" else c["b"]
            groups.setdefault((owner, tuple(s1), tuple(s2), verdict), []).append(j)
        for (owner, s1, s2, (kind, size)), js in groups.items():
            other = c["b"] if owner == c["a"] else c["a"]
            n = len(js)
            holes = f"{n} hole{'s' if n > 1 else ''} across this joint: {names[owner]} {metric.describe(list(s1))}; {names[other]} {metric.describe(list(s2))}."
            if kind == "modelled":
                from interface_check.rules.fasteners import METRIC
                from ..materials import is_plastic
                nominal, tap = METRIC[size][0], METRIC[size][1]
                undersize = min(min(s1), min(s2)) < nominal
                sev = "major" if undersize else "critical"
                title = f"Holes do not fit the modelled {size} screw"
                small = [pid for pid, st in ((_part(graph, owner), s1), (_part(graph, other), s2))
                         if any(d < nominal - 0.05 and abs(d - tap) > metric.TAP_TOL for d in st)]
                plastic = bool(small) and all(is_plastic(graph.part(pid).material, graph.part(pid).process) for pid in small)
                stmt = (f"{holes} The screw modelled through them is {size}: a hole on its path is smaller than the screw "
                        f"and is not its Ø{tap} tap drill.")
                if plastic:
                    sev, title = "info", f"{size} screw self-taps into printed plastic"
                    mats = ", ".join(sorted({graph.part(pid).material or graph.part(pid).process or "plastic" for pid in small}))
                    stmt = (f"{holes} The {size} screw modelled through them cuts its own thread in {mats} "
                            f"(per the BOM) — a normal printed-part detail; confirm the hole size suits the material.")
                elif undersize:
                    stmt += (f" A hole smaller than the screw can work only if it is self-tapped into plastic; in metal or a "
                             f"PCB it needs the Ø{tap} tap drill, or a clearance hole.")
            elif kind == "ambiguous":
                sev, title = "minor", "Mating holes agree only on a non-standard clearance"
                stmt = (f"{holes} They share a size only if the larger is read as an in-between clearance hole; by ISO 273 / "
                        f"ISO 2306 values they take different screws. No fastener is modelled here to settle it.")
            else:
                sev, title = "critical", "Mating holes take different screws"
                stmt = f"{holes} No single metric screw fits both."
            out.append(Finding(
                check_id="IF-FASTENER-SIZE", check_version="1.2.0", domain="interfaces", severity=sev, title=title, statement=stmt,
                measured=Quantity(text=f"Ø{s1[0]:.2f} / Ø{s2[0]:.2f}", unit="mm"),
                expected=Quantity(text=f"both holes accept {size or 'one metric size'}", basis="ISO 273 clearance / ISO 2306 tap drill"),
                evidence=_pair_ev(c, names, [Evidence(type="measurement", points=[j["point"] for j in js], label=f"{n} holes")]),
                recommendation="Size both holes for one screw: clearance on the loose part, tap drill on the threaded one.",
                key=f"size:{c['id']}:{s1}:{s2}"))
        for f in c.get("fits", []):
            shaft_inst = c["a"] if f["shaft_on"] == "a" else c["b"]
            hole_inst = c["b"] if f["shaft_on"] == "a" else c["a"]
            size = next((s for s, dims in fasteners.METRIC.items() if abs(dims[0] - f["shaft_diameter"]) <= 0.05), None)
            if size is None:
                continue
            part_id = next(i.part_id for i in graph.instances if i.id == shaft_inst)
            if not _headed(graph, part_id, f["shaft_diameter"]) or (shaft_inst, round(f["shaft_diameter"], 2)) not in threaded:
                continue                      # a dowel pin or a shaft, not a bolt threaded into anything
            if _head_contact(graph, shaft_inst, f["shaft_diameter"]) != hole_inst:
                continue                      # the threaded part: its hole is the thread, not a clearance
            nominal, tap, fine, medium, coarse = fasteners.METRIC[size]
            h = f["hole_diameter"]
            if fine - 0.05 <= h <= coarse + metric.COARSE_SLACK:
                continue
            if f["clearance"] <= 0.05:
                continue                      # line-to-line: a stepped locating pin in a reamed hole, not a bolt
            tight = h < fine - 0.05
            margin = round((fine - h) if tight else (h - coarse), 3)
            sev = ("major" if margin > 0.15 else "minor") if tight else "minor"
            out.append(Finding(
                check_id="IF-FASTENER-SIZE", check_version="1.2.0", domain="interfaces", severity=sev,
                title="Clearance hole is tight for its bolt" if tight else "Clearance hole is oversize for its bolt",
                statement=f"{names[shaft_inst]} ({size}) clamps {names[hole_inst]} through a Ø{h:.2f} hole. "
                          f"ISO 273 clearance for {size} is Ø{fine} fine to Ø{coarse} coarse"
                          + (f"; {margin:.2f} mm under fine leaves little room for position tolerance." if tight else "."),
                measured=Quantity(value=h, unit="mm"), expected=Quantity(min=fine, max=coarse, unit="mm", basis=f"ISO 273 clearance, {size}"),
                evidence=_pair_ev(c, names, [Evidence(type="measurement", points=[f["point"]], value=h, unit="mm")]),
                recommendation=f"Open the hole to Ø{medium} (medium clearance)" if tight else f"Reduce the hole to Ø{medium} or below",
                key=f"bolt:{c['id']}:{size}:{h}"))
    return out
