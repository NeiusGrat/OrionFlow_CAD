"""D3 Clearance & motion (static): parts that overlap, parts that nearly touch."""
from __future__ import annotations

import numpy as np

from .base import CheckConfig, Evidence, Finding, Quantity, check


def _explained(c: dict) -> tuple[str | None, dict | None]:
    """Is the overlap a modelled thread or a designed interference fit? Judged by where it is."""
    ov = c.get("overlap")
    if not ov:
        return None, None
    cen = np.asarray(ov["centroid"], float)
    for kind, recs in (("thread", c.get("threads", [])), ("press", c.get("press_fits", []))):
        for r in recs:
            a = np.asarray(r["axis"], float)
            d = cen - np.asarray(r["point"], float)
            radial = float(np.linalg.norm(d - a * np.dot(d, a)))
            if radial <= r["shaft_diameter"] / 2 + 0.05:
                return kind, r
    return None, None


@check("CM-INTERFERENCE", "1.1.0", "clearance", "No parts overlap at rest", requires=["contacts"])
def cm_interference(graph, cfg: CheckConfig) -> list[Finding]:
    """Overlapping solids, except modelled threads (screw drawn at full size in a tap-size hole).

    A designed interference fit (a pin or insert up to 1 mm over its hole) is reported as info, so
    it is visible but not alarming. Everything else is a defect, sized by its volume and depth.
    """
    names = {i.id: i.name for i in graph.instances}
    out = []
    for c in graph.contacts:
        ov = c.get("overlap")
        if not ov:
            continue
        kind, rec = _explained(c)
        ev = [Evidence(type="instance", id=c["a"], label=names[c["a"]]), Evidence(type="instance", id=c["b"], label=names[c["b"]]),
              Evidence(type="contact", id=c["id"]), Evidence(type="measurement", points=[ov["centroid"]], value=ov["volume"], unit="mm³")]
        if kind == "thread":
            continue
        if kind == "press":
            out.append(Finding(
                check_id="CM-INTERFERENCE", check_version="1.1.0", domain="clearance", severity="info",
                title="Interference fit by design",
                statement=f"Ø{rec['shaft_diameter']:.2f} on {names[c['a'] if rec['shaft_on'] == 'a' else c['b']]} sits in a "
                          f"Ø{rec['hole_diameter']:.2f} hole: {rec['interference']:.2f} mm of interference "
                          f"({ov['volume']:.2f} mm³). Typical of press-fit pins and heat-set inserts — confirm it is intended.",
                measured=Quantity(value=rec["interference"], unit="mm", text="diametral interference"),
                expected=Quantity(text="intended press or heat-set fit", basis="coaxial boss up to 1 mm over its hole"),
                evidence=ev, recommendation="Confirm the fit class on the drawing.", key=f"press:{c['id']}"))
            continue
        vol = ov["volume"]
        sev = "critical" if vol >= 5.0 else "major" if vol >= 0.5 else "minor"
        ext = ov.get("extent") or []
        small = vol < 0.5
        out.append(Finding(
            check_id="CM-INTERFERENCE", check_version="1.1.0", domain="clearance", severity=sev,
            title="Small overlap at an edge" if small else "Parts overlap",
            statement=(f"{names[c['a']]} and {names[c['b']]} overlap by {vol:.3f} mm³"
                       + (f" (within a {' × '.join(f'{e:.2f}' for e in ext)} mm box)" if ext else "") + ". "
                       + ("Typically a fillet or chamfer that the mating part was not modelled around."
                          if small else "Not a modelled thread or a press fit — the parts cannot both be there.")),
            measured=Quantity(value=vol, unit="mm³"),
            expected=Quantity(max=0.0, unit="mm³", basis="solids may touch, not overlap"),
            evidence=ev, recommendation="Move or trim one part; if the overlap is a deliberate crush (a gasket, a compressed pad), document it.",
            key=f"overlap:{c['id']}"))
    return out


@check("CM-MIN-CLEARANCE", "1.1.0", "clearance", "Minimum clearance between parts", requires=["instances"])
def cm_min_clearance(graph, cfg: CheckConfig) -> list[Finding]:
    """Parts that do not touch but are closer than the minimum clearance for the process."""
    lim = cfg.get("min_clearance_mm")
    names = {i.id: i.name for i in graph.instances}
    out = []
    for c in graph.clearances:
        d = c["min_distance"]
        if d >= lim:
            continue
        if any(abs(f["clearance"] / 2 - d) < 0.02 for f in c.get("fits", [])):
            continue                          # a shank in its clearance hole: the radial gap is the hole doing its job
        ev = [Evidence(type="instance", id=c["a"], label=names[c["a"]]), Evidence(type="instance", id=c["b"], label=names[c["b"]])]
        if c.get("point"):
            ev.append(Evidence(type="measurement", points=[c["point"]], value=d, unit="mm"))
        out.append(Finding(
            check_id="CM-MIN-CLEARANCE", check_version="1.1.0", domain="clearance", severity="major" if d < lim / 3 else "minor",
            title="Clearance below the minimum",
            statement=f"{names[c['a']]} and {names[c['b']]} come within {d:.3f} mm of each other without touching. "
                      f"Tolerance, print shrinkage or deflection can close a gap this small.",
            measured=Quantity(value=d, unit="mm"), expected=Quantity(min=lim, unit="mm", basis=cfg.basis("min_clearance_mm")),
            evidence=ev, recommendation="Open the gap to the minimum clearance, or make the contact intentional.",
            key=f"clr:{min(c['a'], c['b'])}:{max(c['a'], c['b'])}"))
    return out
