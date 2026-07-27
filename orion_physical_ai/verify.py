"""What we can honestly claim about a generated part, and what we cannot.

A generator that silently returns wrong geometry is worse than one that returns
nothing, because the user has no way to tell the two apart. This module turns a
design bundle into an explicit list of checks that were actually run, each
carrying its evidence, so the interface can show proof rather than confidence.

The rule that shapes everything here: **a check appears only when it was
performed.** There is no "assumed pass". A property we did not test is not
listed as a check at all — it is reported under ``measured`` as an observation,
which is a claim about what the kernel said, not a claim that it is correct.
That distinction is the entire product: "verified" has to mean something
narrow and true, or it means nothing.

Note what is deliberately NOT claimed on this path. The agent produces geometry
from OFL code; it does not author a closed-form prediction of its own volume,
so there is nothing to check the measured volume against. The forge path does
(``orion.forge.check_assertions`` compares a frozen closed form against OCC),
and a bundle carrying those rows gets a real ``volume`` check via
``from_assertion_rows``. On the agent path the volume is measured and reported,
never ticked green.
"""

from __future__ import annotations

from typing import Any, Optional

PASS = "pass"
FAIL = "fail"

VERIFIED = "verified"     # every check that ran, passed
REFUSED = "refused"       # at least one check failed
UNPROVEN = "unproven"     # nothing failed, but nothing was provable either


def _check(cid: str, label: str, status: str, detail: str,
           evidence: Optional[dict] = None) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail,
            "evidence": evidence or {}}


def verdict_for(checks: list[dict]) -> str:
    if any(c["status"] == FAIL for c in checks):
        return REFUSED
    return VERIFIED if checks else UNPROVEN


def from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Verification report for an agent design bundle."""
    checks: list[dict] = []
    analysis = bundle.get("analysis") or {}
    props = (analysis.get("properties") or {}) if analysis else {}
    issues = (analysis.get("issues") or []) if analysis else []
    files = bundle.get("files") or {}

    # 1. The builder ran to completion and produced geometry.
    built = bool(bundle.get("success")) and not bundle.get("error")
    has_geom = any(files.get(k) for k in ("step", "stl", "glb"))
    if built and has_geom:
        checks.append(_check(
            "builder", "Builder succeeded", PASS,
            "the feature program compiled and exported geometry",
            {"repair_attempts": bundle.get("repair_attempts", 0)}))
    else:
        checks.append(_check(
            "builder", "Builder succeeded", FAIL,
            bundle.get("error") or "no geometry was produced",
            {"repair_attempts": bundle.get("repair_attempts", 0)}))
        # Nothing downstream is meaningful without a solid.
        return {"verdict": REFUSED, "checks": checks,
                "failed": [c for c in checks if c["status"] == FAIL],
                "measured": {}}

    # 2. Topology: a mesh with open faces is not a solid, whatever it looks
    #    like in a viewer. Only claimed when the analyser actually ran.
    if "watertight" in props:
        wt = bool(props["watertight"])
        checks.append(_check(
            "topology", "Topology valid", PASS if wt else FAIL,
            "closed, watertight solid" if wt
            else "mesh has open faces — this is not a solid",
            {"watertight": wt, "solidity": props.get("solidity")}))

    # 3. Declared envelope, when the plan committed to one. This is a genuine
    #    prediction-vs-measurement check: the plan named a size before the
    #    geometry existed.
    envelope = ((bundle.get("reasoning") or {}).get("envelope_mm")) or None
    bbox = props.get("bbox_mm")
    if envelope and bbox and len(envelope) == len(bbox) == 3:
        over = [round(b - e, 2) for b, e in zip(bbox, envelope)]
        fits = all(b <= e + 0.5 for b, e in zip(bbox, envelope))
        checks.append(_check(
            "envelope", "Fits declared envelope", PASS if fits else FAIL,
            "within the envelope the plan committed to" if fits
            else f"exceeds the declared envelope by {over} mm",
            {"declared_mm": envelope, "measured_mm": bbox}))

    # 4. Manufacturability faults the analyser rates as critical. A warning is
    #    an opinion; a critical issue means the part cannot be made as drawn.
    critical = [i for i in issues if i.get("severity") == "critical"]
    if issues or analysis:
        checks.append(_check(
            "manufacturable", "No critical faults", FAIL if critical else PASS,
            f"{len(critical)} critical manufacturability fault(s)" if critical
            else "no critical faults found",
            {"critical": critical,
             "warnings": sum(1 for i in issues
                             if i.get("severity") == "warning")}))

    measured = {k: props[k] for k in
                ("volume_cm3", "mass_g", "bbox_mm", "center_of_mass_mm")
                if k in props}
    return {"verdict": verdict_for(checks), "checks": checks,
            "failed": [c for c in checks if c["status"] == FAIL],
            "measured": measured}


def from_assertion_rows(rows: list[dict],
                        refused: Optional[list[dict]] = None) -> dict[str, Any]:
    """Verification report for the forge path, where a frozen closed form is
    compared against what the kernel measured.

    ``rows`` are ``orion.forge.check_assertions`` verdicts; ``refused`` are
    preconditions that failed before the build, in which case no geometry was
    produced at all and the guard is the whole story.
    """
    if refused:
        checks = [_check(f"guard:{r.get('id')}", f"Guard {r.get('id')}", FAIL,
                         r.get("why") or "precondition violated",
                         {"value": r.get("target")}) for r in refused]
        return {"verdict": REFUSED, "checks": checks, "failed": checks,
                "measured": {}}

    label = {"body_volume": "Volume matches prediction",
             "body_volume_profile": "Volume matches profile area",
             "body_mesh_converged": "Mesh converges to kernel volume",
             "bbox_extent": "Extent matches prediction",
             "feature_volume": "Feature volume matches prediction",
             "solids": "Single solid", "watertight": "Topology valid",
             "precondition": "Precondition holds"}
    checks = []
    for r in rows:
        kind = r.get("kind", "?")
        ok = bool(r.get("passed"))
        err = r.get("rel_err")
        if r.get("why"):
            detail = r["why"]
        elif err is not None:
            detail = (f"predicted {r.get('target')}, measured "
                      f"{r.get('measured')} (rel err {err:.2e})")
        else:
            detail = f"measured {r.get('measured')}"
        checks.append(_check(f"{kind}:{r.get('id')}",
                             label.get(kind, kind), PASS if ok else FAIL,
                             detail,
                             {"target": r.get("target"),
                              "measured": r.get("measured"),
                              "rel_err": err, "tier": r.get("tier")}))
    return {"verdict": verdict_for(checks), "checks": checks,
            "failed": [c for c in checks if c["status"] == FAIL],
            "measured": {}}
