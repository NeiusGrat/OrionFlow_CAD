"""D3 Clearance & motion (moving): a confirmed joint swept through its range on exact geometry (review/motion.py)."""
from __future__ import annotations

import math

from .base import CheckConfig, Evidence, Finding, Quantity, check

V = "1.0.0"


def _fmt(q: float, kind: str) -> str:
    return f"{math.degrees(q):.2f}°" if kind == "hinge" else f"{q:.3f} mm"


@check("CM-JOINT-SWEEP", V, "clearance", "Joints move through their range without collision", requires=["motion"])
def cm_joint_sweep(graph, cfg: CheckConfig) -> list[Finding]:
    """For every confirmed, swept joint: a collision before a limit, a limit that is a hard stop, a contact that
    rides on the axis but changes at a limit, and the smallest clearance in the range against ``min_clearance_mm``."""
    names = {i.id: i.name for i in graph.instances}
    tol_stop = math.radians(0.5)
    out: list[Finding] = []
    for r in graph.motion["sweeps"]:
        j = r["joint"]
        kind = j["kind"]
        unit = "deg" if kind == "hinge" else "mm"
        conv = (lambda q: math.degrees(q)) if kind == "hinge" else (lambda q: q)
        src = "the sim model's range" if j["source"] == "sim" else "the limits entered for this joint"
        jev = Evidence(type="joint", id=j["key"], label=j["name"])
        coupled = [g["name"] for g in r["groups"][1:]]
        moved = f" (with {', '.join(coupled)} by its coupling)" if coupled else ""
        if r["at_cad_pose"].get("collides"):
            c = r["at_cad_pose"]
            out.append(Finding(
                check_id="CM-JOINT-SWEEP", check_version=V, domain="clearance", severity="major",
                title=f"{j['name']}: collides as soon as it moves",
                statement=f"Moving {j['name']}{moved} by less than {_fmt(r['step'], kind)} from the CAD pose makes "
                          f"{names.get(c['moving'])} and {names.get(c['other'])} collide ({c['kind']}). The sweep could not start.",
                measured=Quantity(value=0, unit=unit, text="travel before collision"),
                expected=Quantity(min=conv(j["lower"]), max=conv(j["upper"]), unit=unit, basis=src),
                evidence=[jev, Evidence(type="instance", id=c["moving"], label=names.get(c["moving"])),
                          Evidence(type="instance", id=c["other"], label=names.get(c["other"]))],
                recommendation="Check the moving set and the joint axis in the Motion lens; a part left behind or "
                               "carried wrongly collides at once.",
                key=f"{j['key']}:rest"))
            continue
        for side in ("upper", "lower"):
            c = r["collisions"].get(side)
            if not c:
                continue
            limit = j[side]
            at_limit = abs(c["q"] - limit) <= tol_stop if kind == "hinge" else abs(c["q"] - limit) <= 0.05
            pair = [Evidence(type="instance", id=c["moving"], label=names.get(c["moving"])),
                    Evidence(type="instance", id=c["other"], label=names.get(c["other"]))]
            if c.get("point"):
                pair.append(Evidence(type="measurement", points=[c["point"]], value=0.0, unit="mm"))
            how = (f"they touch (exact distance 0)" if c["kind"] == "contact" else
                   f"their common volume grows from {c['at_cad_pose']:.3f} to {c['volume']:.3f} mm³")
            if at_limit:
                out.append(Finding(
                    check_id="CM-JOINT-SWEEP", check_version=V, domain="clearance", severity="info",
                    title=f"{j['name']}: the {side} limit is a hard stop",
                    statement=f"At {_fmt(c['q'], kind)}, within {_fmt(tol_stop, kind) if kind == 'hinge' else '0.05 mm'} of "
                              f"the {side} limit {_fmt(limit, kind)} ({src}), {names.get(c['moving'])} meets "
                              f"{names.get(c['other'])}: {how}. A limit at contact is a stop by design, or the limit was "
                              "set from the geometry.",
                    evidence=[jev] + pair, key=f"{j['key']}:{side}:stop"))
                continue
            out.append(Finding(
                check_id="CM-JOINT-SWEEP", check_version=V, domain="clearance", severity="major",
                title=f"{j['name']}: collides before its {side} limit",
                statement=f"Swept from the CAD pose ({_fmt(j['cad_q'], kind)}) toward the {side} limit "
                          f"{_fmt(limit, kind)}{moved}, {names.get(c['moving'])} meets {names.get(c['other'])} at "
                          f"{_fmt(c['q'], kind)}: {how}. Clear until {_fmt(c['clear_until_q'], kind)}. "
                          f"{src.capitalize()} allows {_fmt(abs(limit - c['q']), kind)} more travel than the parts do.",
                measured=Quantity(value=round(conv(c["q"]), 3), unit=unit, text="first collision"),
                expected=Quantity(value=round(conv(limit), 3), unit=unit, basis=src),
                evidence=[jev] + pair,
                recommendation=("Set the sim joint range to the collision angle, or remove material / add relief "
                                "where the parts meet." if j["source"] == "sim" else
                                "Reduce the limit to the collision angle, or relieve the parts where they meet."),
                key=f"{j['key']}:{side}:collision"))
        for side in ("upper", "lower"):
            for o in r["ends"][side].get("riding_overlap", []):
                if o.get("grows"):
                    out.append(Finding(
                        check_id="CM-JOINT-SWEEP", check_version=V, domain="clearance", severity="major",
                        title=f"{j['name']}: a bearing contact changes at the {side} end",
                        statement=f"{names.get(o['moving'])} rides on {names.get(o['other'])} about the axis, but at "
                                  f"{_fmt(r['ends'][side]['q'], kind)} their common volume is {o['volume']:.3f} mm³ "
                                  f"(at the CAD pose {o['at_cad_pose']:.3f} mm³). The contact is not a surface of "
                                  "revolution about this axis: check the axis.",
                        measured=Quantity(value=o["volume"], unit="mm³"),
                        expected=Quantity(value=o["at_cad_pose"], unit="mm³", basis="unchanged by rotation about the axis"),
                        evidence=[jev, Evidence(type="instance", id=o["moving"], label=names.get(o["moving"])),
                                  Evidence(type="instance", id=o["other"], label=names.get(o["other"]))],
                        key=f"{j['key']}:{side}:ride:{o['moving']}:{o['other']}"))
        mc = r.get("min_clearance")
        lim = cfg.get("min_clearance_mm")
        if mc and mc.get("pair") and 0 < mc["distance"] < lim:
            a, b = mc["pair"]
            out.append(Finding(
                check_id="CM-JOINT-SWEEP", check_version=V, domain="clearance", severity="minor",
                title=f"{j['name']}: tight clearance in motion",
                statement=f"Over the swept range{moved} the closest approach is {mc['distance']:.3f} mm, between "
                          f"{names.get(a)} and {names.get(b)} at {_fmt(mc['q'], kind)}.",
                measured=Quantity(value=mc["distance"], unit="mm", text="minimum clearance in the range"),
                expected=Quantity(min=lim, unit="mm", basis=cfg.basis("min_clearance_mm")),
                evidence=[jev, Evidence(type="instance", id=a, label=names.get(a)), Evidence(type="instance", id=b, label=names.get(b))],
                recommendation="Allow for print and machining tolerance, or accept with the process stated.",
                key=f"{j['key']}:clearance"))
    return out
