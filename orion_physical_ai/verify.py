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

VERIFIED = "verified"  # every check that ran, passed
REFUSED = "refused"  # at least one check failed
UNPROVEN = "unproven"  # nothing failed, but nothing was provable either


def _check(
    cid: str, label: str, status: str, detail: str, evidence: Optional[dict] = None
) -> dict:
    return {
        "id": cid,
        "label": label,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


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
        checks.append(
            _check(
                "builder",
                "Builder succeeded",
                PASS,
                "the feature program compiled and exported geometry",
                {"repair_attempts": bundle.get("repair_attempts", 0)},
            )
        )
    else:
        checks.append(
            _check(
                "builder",
                "Builder succeeded",
                FAIL,
                bundle.get("error") or "no geometry was produced",
                {"repair_attempts": bundle.get("repair_attempts", 0)},
            )
        )
        # Nothing downstream is meaningful without a solid.
        return {
            "verdict": REFUSED,
            "checks": checks,
            "failed": [c for c in checks if c["status"] == FAIL],
            "measured": {},
        }

    # 2. Topology: a mesh with open faces is not a solid, whatever it looks
    #    like in a viewer. Only claimed when the analyser actually ran.
    if "watertight" in props:
        wt = bool(props["watertight"])
        checks.append(
            _check(
                "topology",
                "Topology valid",
                PASS if wt else FAIL,
                (
                    "closed, watertight solid"
                    if wt
                    else "mesh has open faces — this is not a solid"
                ),
                {"watertight": wt, "solidity": props.get("solidity")},
            )
        )

    # 3. Declared envelope, when the plan committed to one. This is a genuine
    #    prediction-vs-measurement check: the plan named a size before the
    #    geometry existed.
    envelope = ((bundle.get("reasoning") or {}).get("envelope_mm")) or None
    bbox = props.get("bbox_mm")
    if envelope and bbox and len(envelope) == len(bbox) == 3:
        over = [round(b - e, 2) for b, e in zip(bbox, envelope)]
        fits = all(b <= e + 0.5 for b, e in zip(bbox, envelope))
        checks.append(
            _check(
                "envelope",
                "Fits declared envelope",
                PASS if fits else FAIL,
                (
                    "within the envelope the plan committed to"
                    if fits
                    else f"exceeds the declared envelope by {over} mm"
                ),
                {"declared_mm": envelope, "measured_mm": bbox},
            )
        )

    # 4. Manufacturability faults the analyser rates as critical. A warning is
    #    an opinion; a critical issue means the part cannot be made as drawn.
    critical = [i for i in issues if i.get("severity") == "critical"]
    if issues or analysis:
        checks.append(
            _check(
                "manufacturable",
                "No critical faults",
                FAIL if critical else PASS,
                (
                    f"{len(critical)} critical manufacturability fault(s)"
                    if critical
                    else "no critical faults found"
                ),
                {
                    "critical": critical,
                    "warnings": sum(
                        1 for i in issues if i.get("severity") == "warning"
                    ),
                },
            )
        )

    measured = {
        k: props[k]
        for k in ("volume_cm3", "mass_g", "bbox_mm", "center_of_mass_mm")
        if k in props
    }
    return {
        "verdict": verdict_for(checks),
        "checks": checks,
        "failed": [c for c in checks if c["status"] == FAIL],
        "measured": measured,
    }


def from_assertion_rows(
    rows: list[dict],
    refused: Optional[list[dict]] = None,
    measured: Optional[dict] = None,
) -> dict[str, Any]:
    """Verification report for the forge path, where a frozen closed form is
    compared against what the kernel measured.

    ``rows`` are ``orion.forge.check_assertions`` verdicts; ``refused`` are
    preconditions that failed before the build, in which case no geometry was
    produced at all and the guard is the whole story. ``measured`` carries
    observations (volume, extent) for display — they are reported, never
    ticked, unless a row above actually checked them.
    """
    if refused:
        checks = [
            _check(
                f"guard:{r.get('id')}",
                f"Guard {r.get('id')}",
                FAIL,
                r.get("why") or "precondition violated",
                {"value": r.get("target")},
            )
            for r in refused
        ]
        return {"verdict": REFUSED, "checks": checks, "failed": checks, "measured": {}}

    label = {
        "body_volume": "Volume matches prediction",
        "body_volume_profile": "Volume matches profile area",
        "body_mesh_converged": "Mesh converges to kernel volume",
        "bbox_extent": "Extent matches prediction",
        "feature_volume": "Feature volume matches prediction",
        "solids": "Single solid",
        "watertight": "Topology valid",
        "precondition": "Precondition holds",
    }
    checks = []
    for r in rows:
        kind = r.get("kind", "?")
        ok = bool(r.get("passed"))
        err = r.get("rel_err")
        if r.get("why"):
            detail = r["why"]
        elif err is not None:
            detail = (
                f"predicted {r.get('target')}, measured "
                f"{r.get('measured')} (rel err {err:.2e})"
            )
        elif kind == "precondition":
            # A precondition has no measurement — it is a guard the model
            # authored and the resolved variables satisfy. Reporting it as
            # "measured None" reads like a check that failed to run.
            detail = f"holds at {r.get('target')}"
        else:
            detail = f"measured {r.get('measured')}"
        checks.append(
            _check(
                f"{kind}:{r.get('id')}",
                label.get(kind, kind),
                PASS if ok else FAIL,
                detail,
                {
                    "target": r.get("target"),
                    "measured": r.get("measured"),
                    "rel_err": err,
                    "tier": r.get("tier"),
                },
            )
        )
    checks.extend(solid_validity_checks(measured))

    return {
        "verdict": verdict_for(checks),
        "checks": checks,
        "failed": [c for c in checks if c["status"] == FAIL],
        "measured": dict(measured or {}),
    }


#: Whether the kernel's own opinion of the solid counts towards the verdict.
#:
#: **On.** Enabled 2026-08-05 together with a re-measurement of every published
#: figure — see ``solid_validity_checks`` for what it gates and why flipping it
#: alone was not enough.
COUNT_SOLID_VALIDITY = True


def solid_validity_checks(measured: Optional[dict]) -> list[dict]:
    """The kernel's own opinion of the shape, as checks that count.

    **The gap this closes.** ``check_assertions`` grades the closed form against
    the measurement: volume, extent, the guards the model authored. None of it
    asks the kernel whether the solid it produced is geometrically sound, or
    whether it is even one object. ``measured["valid"]`` and
    ``measured["solids"]`` carry exactly that, and until now nothing consumed
    them — so a part could satisfy every assertion to 1e-16 and still be
    invalid, or in fourteen disconnected pieces, and be reported VERIFIED.

    Neither is theoretical. A Blueprint with two overlapping holes built, came
    back ``watertight: true``, ``solids: 1``, volume matching the closed form to
    ten decimal places — and ``valid: false``: OCC had removed two full disks
    rather than merging the overlapping wires, so the arithmetic agreed while
    the topology did not. Separately, a shelled enclosure built fillet-then-
    shell came back as 14 solids with a face of negative area, and passed.

    **Two checks, not one.** ``watertight`` and a ``solids`` *assertion* are the
    existing checks that look closest to these and neither substitutes:
    watertight was true for both invalid solids above, and a ``solids``
    assertion only runs when the model happened to author one. These run on
    every build, authored or not.

    **``None`` is not failure.** A measurement that never ran is unknown, not
    bad — the same rule the rest of this module follows ("a check that did not
    run is not a check that passed"; equally, it is not one that failed).
    Records predating the measurement pass carry ``None`` and must not be
    retroactively refused.
    """
    if not COUNT_SOLID_VALIDITY or not measured:
        return []

    checks: list[dict] = []

    if measured.get("valid") is not None:
        ok = bool(measured["valid"])
        checks.append(
            _check(
                "solid:valid",
                "Solid is geometrically valid",
                PASS if ok else FAIL,
                (
                    "OCC reports the shape as valid"
                    if ok
                    else "OCC reports the shape as invalid — the assertions can "
                    "still agree, because a wrong topology can have a right volume"
                ),
                {"measured": measured["valid"]},
            )
        )

    n = measured.get("solids")
    if n is not None:
        # A PartDesign Body is one contiguous solid by definition. More than one
        # means an operation shattered it; zero means nothing survived. Either
        # way the part is not the thing the design plan described, however well
        # the volume happens to agree. Assemblies would legitimately have many —
        # they are not on this path, and the occurrence level that would carry
        # them (``#o1``) is defined and unused.
        ok = n == 1
        checks.append(
            _check(
                "solid:count",
                "Part is a single connected solid",
                PASS if ok else FAIL,
                (
                    "the body is one connected solid"
                    if ok
                    else (
                        f"the body is in {n} disconnected pieces"
                        if n > 1
                        else "the body contains no solid"
                    )
                ),
                {"measured": n, "expected": 1},
            )
        )

    return checks
