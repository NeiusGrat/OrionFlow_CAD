"""D5 Sim fidelity: does the URDF/MJCF describe the CAD it was made from?"""
from __future__ import annotations

import math

import numpy as np

from .base import CheckConfig, Evidence, Finding, Quantity, check


def _doc(graph):
    return next((d for d in graph.documents if d.get("kind") == "sim"), None)


def _ev_body(b: dict, names: dict) -> list[Evidence]:
    return ([Evidence(type="joint", id=b["body"], label=f"sim body {b['body']}")]
            + [Evidence(type="instance", id=i, label=names.get(i, i)) for i in b["instances"][:8]])


@check("SIM-MAP", "1.0.0", "sim", "Sim bodies map to the CAD", requires=["sim"])
def sim_map(graph, cfg: CheckConfig) -> list[Finding]:
    """Every sim body has CAD parts, every CAD part is in a sim body, and the sim was built from this STEP."""
    doc = _doc(graph)
    a = doc["analysis"]
    names = {i.id: i.name for i in graph.instances}
    out = []
    man = doc.get("manifest") or {}
    src = man.get("source_sha256")
    if src and src != graph.source.sha256:
        out.append(Finding(
            check_id="SIM-MAP", check_version="1.0.0", domain="sim", severity="critical",
            title="Sim model was built from a different STEP",
            statement=f"{man.get('file')} records source SHA-256 {src[:12]}…; this revision's STEP is {graph.source.sha256[:12]}…. "
                      f"The sim describes another version of the geometry.",
            measured=Quantity(text=src[:16]), expected=Quantity(text=graph.source.sha256[:16], basis="this revision's STEP"),
            evidence=[Evidence(type="file", id=graph.source.name, label=graph.source.name, sha256=graph.source.sha256)],
            recommendation="Regenerate the sim model from this STEP.", key="source-sha"))
    mapped = set()
    for b in a["bodies"]:
        mapped.update(b["instances"])
        if not b["instances"] and b.get("sim") and (b["sim"] or {}).get("mass", 0) > 0:
            out.append(Finding(
                check_id="SIM-MAP", check_version="1.0.0", domain="sim", severity="major",
                title="Sim body has no CAD parts",
                statement=f"Body {b['body']} ({b['sim']['mass']:.4g} kg in the sim) could not be matched to any CAD instance.",
                measured=Quantity(value=0, unit="CAD instances"), expected=Quantity(min=1, unit="CAD instances", basis="every massive sim body"),
                evidence=[Evidence(type="joint", id=b["body"], label=f"sim body {b['body']}")],
                recommendation="Pair the body with its CAD parts in the Sim lens.", key=f"empty:{b['body']}"))
    left = [i for i in graph.instances if i.id not in mapped]
    if left:
        out.append(Finding(
            check_id="SIM-MAP", check_version="1.0.0", domain="sim", severity="major",
            title="CAD parts missing from the sim model",
            statement=f"{len(left)} CAD instance{'s are' if len(left) > 1 else ' is'} in no sim body: "
                      + ", ".join(sorted({i.name for i in left})[:8]) + ("…" if len(left) > 8 else "")
                      + ". Their mass and inertia are missing from the simulation.",
            measured=Quantity(value=len(left), unit="instances"), expected=Quantity(value=0, unit="instances", basis="every CAD part simulated"),
            evidence=[Evidence(type="instance", id=i.id, label=i.name) for i in left[:10]],
            recommendation="Add the parts to a body, or pair them in the Sim lens.", key="unmapped"))
    return out


@check("SIM-COUNT", "1.0.0", "sim", "Body and solid counts reconcile", requires=["sim"])
def sim_count(graph, cfg: CheckConfig) -> list[Finding]:
    """Source solids per sim body against CAD instances, so merged and split solids are visible."""
    doc = _doc(graph)
    man = doc.get("manifest")
    if not man:
        return []
    per_body: dict[str, int] = {}
    for m in man["meshes"].values():
        per_body[m.get("body", "?")] = per_body.get(m.get("body", "?"), 0) + len(m.get("leaf_features", []))
    a = doc["analysis"]
    rows = []
    for b in a["bodies"]:
        rows.append((b["body"], len(b["instances"])))
    total_leaves, total_inst = sum(per_body.values()), sum(n for _, n in rows)
    if total_leaves == total_inst:
        return []
    return [Finding(
        check_id="SIM-COUNT", check_version="1.0.0", domain="sim", severity="info",
        title="Sim source solids and CAD instances differ in count",
        statement=f"The sim's manifest lists {total_leaves} source solids "
                  f"({', '.join(f'{k} {v}' for k, v in sorted(per_body.items()))}); the CAD has {total_inst} placed instances "
                  f"({', '.join(f'{k} {v}' for k, v in rows)}). Parts exported as several solids (a servo, a camera) "
                  f"count once in the CAD and several times in the sim source — check the difference is only that.",
        measured=Quantity(value=total_inst, unit="CAD instances"), expected=Quantity(value=total_leaves, unit="sim source solids", basis=man["file"]),
        evidence=[Evidence(type="file", id=man["file"], label=man["file"])],
        recommendation="No action if the difference is multi-solid purchased parts.", key="count")]


@check("SIM-MASS", "1.0.0", "sim", "Body masses match the CAD", requires=["sim"])
def sim_mass(graph, cfg: CheckConfig) -> list[Finding]:
    """Sim body mass against the CAD mass of the parts mapped to it (volume x density, or a stated mass)."""
    doc = _doc(graph)
    names = {i.id: i.name for i in graph.instances}
    tol = cfg.get("sim_mass_rel")
    out = []
    for b in doc["analysis"]["bodies"]:
        sim, cad = b.get("sim"), b.get("cad")
        if not sim or not b["instances"]:
            continue
        if not cad or not cad.get("complete"):
            miss = sorted({names.get(i, i) for i in b["missing"]})
            out.append(Finding(
                check_id="SIM-MASS", check_version="1.0.0", domain="sim", severity="info",
                title="CAD mass of a body is incomplete",
                statement=f"Body {b['body']}: {len(miss)} part{'s have' if len(miss) > 1 else ' has'} no known mass "
                          f"({', '.join(miss[:6])}), so the CAD total ({(cad or {}).get('mass', 0):.4g} kg so far) cannot be compared "
                          f"with the sim's {sim['mass']:.4g} kg.",
                measured=Quantity(value=(cad or {}).get("mass", 0), unit="kg (partial)"),
                expected=Quantity(value=sim["mass"], unit="kg", basis="sim model"),
                evidence=_ev_body(b, names),
                recommendation="Give those parts a material, density or measured mass (Sim lens → part masses).",
                key=f"incomplete:{b['body']}"))
            continue
        rel = (cad["mass"] - sim["mass"]) / max(sim["mass"], 1e-12)
        if abs(rel) <= tol:
            continue
        fdm = [graph.part(next(i.part_id for i in graph.instances if i.id == iid)) for iid in b["instances"]]
        printed = sorted({p.name for p in fdm if (p.process or "").startswith("FDM")})
        note = (f" {len(printed)} of its parts are 3D-printed and their CAD mass assumes solid material; a sim that "
                f"models infill would be lighter.") if printed and rel > 0 else ""
        out.append(Finding(
            check_id="SIM-MASS", check_version="1.0.0", domain="sim", severity="major" if abs(rel) < 0.25 else "critical",
            title="Sim body mass differs from the CAD",
            statement=f"Body {b['body']}: the sim says {sim['mass']:.4g} kg, the CAD parts add up to {cad['mass']:.4g} kg "
                      f"({rel * 100:+.1f} %).{note}",
            measured=Quantity(value=round(sim["mass"], 6), unit="kg (sim)"),
            expected=Quantity(value=round(cad["mass"], 6), min=round(cad["mass"] * (1 - tol), 6), max=round(cad["mass"] * (1 + tol), 6),
                              unit="kg", basis=f"CAD volume × density; {cfg.basis('sim_mass_rel')}"),
            evidence=_ev_body(b, names),
            recommendation="Update the sim inertial (Sim lens has the corrected block) or the part materials.",
            key=f"mass:{b['body']}"))
    return out


@check("SIM-COM", "1.0.0", "sim", "Centres of mass match the CAD", requires=["sim"])
def sim_com(graph, cfg: CheckConfig) -> list[Finding]:
    """COM in the body frame (rigid bodies) or as radius and height about the joint axis (hinged bodies)."""
    doc = _doc(graph)
    if not doc.get("registration"):
        return []
    names = {i.id: i.name for i in graph.instances}
    tol = cfg.get("sim_com_mm")
    out = []
    for b in doc["analysis"]["bodies"]:
        sim, cad = b.get("sim"), b.get("cad")
        if not sim or not cad or not cad.get("complete") or "com_m" not in cad:
            continue
        if b["frame"] == "hinge" and "cyl_m" in cad and b.get("sim_cyl_m"):
            dr = (cad["cyl_m"][0] - b["sim_cyl_m"][0]) * 1000
            dh = (cad["cyl_m"][1] - b["sim_cyl_m"][1]) * 1000
            d = math.hypot(dr, dh)
            how = (f"radius from the joint axis {b['sim_cyl_m'][0] * 1000:.2f} mm (sim) vs {cad['cyl_m'][0] * 1000:.2f} mm (CAD), "
                   f"height along it {b['sim_cyl_m'][1] * 1000:.2f} vs {cad['cyl_m'][1] * 1000:.2f} mm; the CAD has the body posed "
                   f"{b.get('pose_offset_deg', 0):+.1f}° from the sim zero")
        else:
            d = float(np.linalg.norm(np.subtract(cad["com_m"], sim["com"]))) * 1000
            how = (f"sim ({', '.join(f'{v * 1000:.2f}' for v in sim['com'])}) mm vs CAD "
                   f"({', '.join(f'{v * 1000:.2f}' for v in cad['com_m'])}) mm in the body frame")
        if d <= tol:
            continue
        out.append(Finding(
            check_id="SIM-COM", check_version="1.0.0", domain="sim", severity="major" if d < 10 else "critical",
            title="Sim centre of mass is off the CAD",
            statement=f"Body {b['body']}: the centre of mass is {d:.2f} mm from the CAD's — {how}.",
            measured=Quantity(value=round(d, 3), unit="mm"), expected=Quantity(max=tol, unit="mm", basis=cfg.basis("sim_com_mm")),
            evidence=_ev_body(b, names),
            recommendation="Replace the body's inertial with the corrected block in the Sim lens.", key=f"com:{b['body']}"))
    return out


@check("SIM-INERTIA", "1.0.0", "sim", "Inertia tensors match the CAD", requires=["sim"])
def sim_inertia(graph, cfg: CheckConfig) -> list[Finding]:
    """Principal moments (independent of pose and frame) of the sim against the CAD."""
    doc = _doc(graph)
    names = {i.id: i.name for i in graph.instances}
    tol = cfg.get("sim_inertia_rel")
    out = []
    for b in doc["analysis"]["bodies"]:
        sim, cad = b.get("sim"), b.get("cad")
        if not sim or not cad or not cad.get("complete") or "principal_kg_m2" not in cad:
            continue
        ps = sorted(float(x) for x in np.linalg.eigvalsh(np.asarray(sim["inertia"], float)))
        pc = cad["principal_kg_m2"]
        rels = [(s - c) / max(c, 1e-15) for s, c in zip(ps, pc)]
        worst = max(rels, key=abs)
        if abs(worst) <= tol:
            continue
        out.append(Finding(
            check_id="SIM-INERTIA", check_version="1.0.0", domain="sim", severity="major" if abs(worst) < 0.5 else "critical",
            title="Sim inertia differs from the CAD",
            statement=f"Body {b['body']}: principal moments {', '.join(f'{v:.3e}' for v in ps)} kg·m² in the sim vs "
                      f"{', '.join(f'{v:.3e}' for v in pc)} from the CAD (worst {worst * 100:+.0f} %).",
            measured=Quantity(value=round(worst, 4), unit="relative"), expected=Quantity(max=tol, unit="relative", basis=cfg.basis("sim_inertia_rel")),
            evidence=_ev_body(b, names),
            recommendation="Replace the body's inertial with the corrected block in the Sim lens.", key=f"inertia:{b['body']}"))
    return out


@check("SIM-AXIS", "1.0.0", "sim", "Joint axes match the CAD", requires=["sim"])
def sim_axis(graph, cfg: CheckConfig) -> list[Finding]:
    """Each hinge axis against the shaft/bore the CAD hinge actually turns on (a coaxial cylinder shared by both bodies)."""
    doc = _doc(graph)
    if not doc.get("registration"):
        return []
    tol = cfg.get("sim_axis_deg")
    out = []
    for j in doc["analysis"]["joints"]:
        cands = j.get("cad_axes") or []
        if j["type"] != "hinge" or not cands:
            continue
        c = cands[0]
        a = np.asarray(j["axis_root"], float)
        b = np.asarray(c["axis_root"], float)
        ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(a, b))) / (np.linalg.norm(a) * np.linalg.norm(b)))))
        d = np.asarray(c["point_root"], float) - np.asarray(j["pos_root"], float)
        offset = float(np.linalg.norm(d - b * np.dot(d, b))) * 1000
        if ang <= tol and offset <= 1.0:
            continue
        out.append(Finding(
            check_id="SIM-AXIS", check_version="1.0.0", domain="sim", severity="major",
            title="Joint axis is off the CAD hinge",
            statement=f"Joint {j['name']}: {ang:.2f}° from, and {offset:.2f} mm away from, the Ø{c['diameter']:g} shaft/bore the "
                      f"CAD hinge turns on.",
            measured=Quantity(value=round(ang, 3), unit="°", text=f"offset {offset:.2f} mm"),
            expected=Quantity(max=tol, unit="°", basis=cfg.basis("sim_axis_deg")),
            evidence=[Evidence(type="joint", id=j["name"], label=f"joint {j['name']}"),
                      Evidence(type="measurement", points=[[v * 1000 for v in c["point_root"]]], label=f"Ø{c['diameter']:g} hinge bore")],
            recommendation="Set the joint axis and origin from the shaft bore.", key=f"axis:{j['name']}"))
    return out
