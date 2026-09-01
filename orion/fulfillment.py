"""Did the built solid actually get the features that were asked for?

Answered from the topology sidecar — OCC's own account of the shape it produced,
written by ``orion/topology_fc.py`` inside FreeCAD. Every number used here came
off a face: its surface type, its radius, the anchor point on its axis. Nothing
here reads the model's reply, the Blueprint's own volume expression, or anything
else that was computed from the same requirements the feature is supposed to
satisfy. That independence is the whole point — the reason a blank plate passed
its volume assertion is that the closed form was derived from the absent holes,
so the two agreed with each other and neither looked at the solid.

The four states an obligation can reach, and they are not the same claim:

    requested      the user asked for it            (an obligation exists)
    represented    the frozen template declares it  (the contract carries it)
    instantiated   the build produced that feature  (topology attributes faces)
    verified       the geometry agrees on count, size and placement

Only the last is evidence the feature is right. ``verified`` requires the other
three, and a check that cannot reach it says so rather than passing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from . import obligations as O

#: Millimetres. A radius or a position closer than this to its target counts as
#: agreeing. Chosen against the sidecar's own rounding (six decimals) and the
#: kernel's tessellation-independent exactness: these are analytic surface
#: parameters, not mesh measurements, so they agree to machine precision when
#: they agree at all. Loose enough for the two-decimal numbers a user types
#: (a 47.14 mm bolt circle), tight enough that 5 mm never passes for 6.
ABS_TOL_MM = 0.05

#: Two axes closer than this in the plane are the same hole seen twice — a
#: counterbore contributes two coaxial cylindrical faces, and counting them as
#: two holes would report a four-hole pattern as eight.
COAXIAL_TOL_MM = 0.05


@dataclass
class Fulfillment:
    """One obligation, and what the built geometry says about it."""

    obligation: dict
    requested: bool = True
    represented: bool = False
    instantiated: bool = False
    observed: bool = False
    verified: bool = False
    #: "pass" — the geometry agrees; "fail" — the geometry contradicts the
    #: request; "warn" — it could not be established either way.
    status: str = "warn"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.obligation.get("id"),
            "kind": self.obligation.get("kind"),
            "label": self.obligation.get("label"),
            "requested": self.requested,
            "represented": self.represented,
            "instantiated": self.instantiated,
            "observed": self.observed,
            "verified": self.verified,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------- #
# reading cylinders out of the sidecar
# --------------------------------------------------------------------------- #
def _faces(topology: Optional[dict]) -> list[dict]:
    faces = (topology or {}).get("faces")
    return faces if isinstance(faces, list) else []


def _body_bbox(topology: Optional[dict]) -> Optional[list]:
    for occurrence in (topology or {}).get("occurrences") or []:
        bbox = occurrence.get("bbox")
        if bbox and len(bbox) == 6:
            return bbox
    return None


def _unit(v) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def basis_for(direction) -> tuple[tuple, tuple]:
    """Two orthonormal vectors spanning the plane perpendicular to ``direction``.

    Chosen deterministically — seeded from the world axis least aligned with the
    direction — so the same hole pattern always maps to the same 2D coordinates
    whichever way its axis points. For a Z-pointing hole this gives (X, Y),
    which is what a bolt circle drawn on the XY plane expects.
    """
    d = _unit(direction)
    seed = min(
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        key=lambda w: abs(_dot(d, w)),
    )
    u = _unit(_cross(d, seed))
    v = _unit(_cross(d, u))
    return u, v


@dataclass(frozen=True)
class Axis:
    """One hole axis: a direction and a point on it."""

    direction: tuple
    point: tuple

    def coaxial_with(self, other: "Axis", tol: float = COAXIAL_TOL_MM) -> bool:
        """Same line, allowing for the two faces of one hole and either sign.

        A counterbore contributes two coaxial cylindrical faces of different
        radii; a hole split by a boolean contributes several. Counting *lines*
        rather than faces is what makes the number mean "how many holes".
        """
        if abs(abs(_dot(self.direction, other.direction)) - 1.0) > 1e-6:
            return False
        delta = tuple(a - b for a, b in zip(self.point, other.point))
        along = _dot(delta, self.direction)
        perpendicular = tuple(
            d - along * a for d, a in zip(delta, self.direction)
        )
        return math.sqrt(_dot(perpendicular, perpendicular)) <= tol

    def plane_coords(self, u, v, origin) -> tuple[float, float]:
        rel = tuple(p - o for p, o in zip(self.point, origin))
        return (_dot(rel, u), _dot(rel, v))


def _body_centre(topology: Optional[dict]) -> Optional[tuple]:
    """The body's own centre, from its bounding box.

    The datum a bolt circle is measured from. Taken from the *solid* rather
    than from the Blueprint, so the placement check has an origin the contract
    did not supply.
    """
    bbox = _body_bbox(topology)
    if not bbox:
        return None
    return tuple((bbox[i] + bbox[i + 3]) / 2.0 for i in range(3))


def cylinder_axes(topology: Optional[dict], radius: float,
                  tol: float = ABS_TOL_MM) -> list:
    """Distinct hole axes whose cylindrical radius matches the request.

    Axis-agnostic on purpose. An earlier version projected every anchor onto
    XY, which is correct only for holes drilled along Z — an L-bracket's bolt
    pattern runs along X, and four holes at (y, z) = (±20, 20) and (±20, 60)
    collapsed onto two XY points. It reported four requested and two found, and
    refused a part that was perfectly correct. Two cylinders are the same hole
    when their directions are parallel and the offset between their anchors has
    no component across that direction.
    """
    seen: list[Axis] = []
    for face in _faces(topology):
        if (face.get("surface") or "") != "Cylinder":
            continue
        r = face.get("radius")
        if not isinstance(r, (int, float)) or abs(float(r) - radius) > tol:
            continue
        anchor = face.get("position") or face.get("center")
        direction = face.get("axis")
        if not anchor or len(anchor) < 3 or not direction or len(direction) < 3:
            continue
        axis = Axis(_unit([float(c) for c in direction[:3]]),
                    tuple(float(c) for c in anchor[:3]))
        if not any(axis.coaxial_with(other) for other in seen):
            seen.append(axis)
    return seen


def cylinder_radii(topology: Optional[dict]) -> list[float]:
    """Every distinct cylindrical radius in the solid, for reporting a miss.

    What a failure needs in order to be actionable: "you asked for 2.5 mm and
    the part has 4.2 mm" points at the bug; "not found" does not.
    """
    out: list[float] = []
    for face in _faces(topology):
        if (face.get("surface") or "") != "Cylinder":
            continue
        r = face.get("radius")
        if isinstance(r, (int, float)) and not any(
            abs(float(r) - k) <= ABS_TOL_MM for k in out
        ):
            out.append(round(float(r), 4))
    return sorted(out)


def dominant_direction(axes: list) -> tuple:
    """The direction most axes share, sign-normalised.

    A pattern can include a stray coaxial neighbour; the plane the pattern
    lives in is the one most of it agrees on.
    """
    groups: list[list[Axis]] = []
    for axis in axes:
        for group in groups:
            if abs(abs(_dot(axis.direction, group[0].direction)) - 1.0) <= 1e-6:
                group.append(axis)
                break
        else:
            groups.append([axis])
    biggest = max(groups, key=len)
    d = biggest[0].direction
    # Sign-normalise so the derived basis does not flip between builds.
    for component in d:
        if abs(component) > 1e-9:
            return d if component > 0 else tuple(-c for c in d)
    return d


# --------------------------------------------------------------------------- #
# placement
# --------------------------------------------------------------------------- #
def _check_placement(placement: dict, axes: list, centre) -> tuple[bool, str, dict]:
    """Does the pattern sit where the request said, measured in its own plane.

    Everything is done in the plane perpendicular to the holes' shared axis, so
    a bolt circle drilled along X is checked exactly as one drilled along Z.
    ``centre`` is the body's own bbox centre, projected into that same plane —
    a datum the contract did not supply.
    """
    form = placement.get("form")
    if not axes:
        return False, "no axes of the requested size to measure", {}
    if centre is None:
        return False, "no body centre to measure against", {}

    direction = dominant_direction(axes)
    u, v = basis_for(direction)
    points = [a.plane_coords(u, v, centre) for a in axes]

    if form == O.CENTRED:
        offset = math.hypot(*points[0])
        ok = offset <= ABS_TOL_MM
        return ok, f"axis sits {offset:.4f} mm off the body centre", {
            "offset_mm": round(offset, 4)
        }

    if form == O.BOLT_CIRCLE:
        want = placement.get("radius")
        if want is None:
            return False, "no bolt circle radius to measure against", {}
        radii = [math.hypot(*p) for p in points]
        worst = max(abs(r - want) for r in radii)
        ok = worst <= ABS_TOL_MM
        return ok, (
            f"measured bolt circle radius {min(radii):.4f}–{max(radii):.4f} mm "
            f"against {want:.4f} mm"
        ), {"measured_radii_mm": [round(r, 4) for r in radii],
            "expected_radius_mm": want}

    if form == O.GRID:
        pitch = placement.get("pitch") or []
        if len(pitch) != 2 or None in pitch:
            return False, "no pitch to measure against", {}
        span_u = max(p[0] for p in points) - min(p[0] for p in points)
        span_v = max(p[1] for p in points) - min(p[1] for p in points)
        # A square pattern is the same pattern whichever way round it is read,
        # and the plane's basis is chosen by geometry rather than by the
        # request — so the two spans are matched as a set.
        measured = sorted((span_u, span_v))
        expected = sorted(pitch)
        ok = all(
            abs(m - e) <= ABS_TOL_MM for m, e in zip(measured, expected)
        )
        return ok, (
            f"measured pattern {measured[0]:.4f} x {measured[1]:.4f} mm against "
            f"{expected[0]:.4f} x {expected[1]:.4f} mm"
        ), {"measured_pitch_mm": [round(m, 4) for m in measured],
            "expected_pitch_mm": expected}

    if form == O.LINE:
        if len(points) < 2:
            return True, "a single axis needs no spacing check", {}
        # Along whichever in-plane direction the pattern actually spreads.
        spread_u = max(p[0] for p in points) - min(p[0] for p in points)
        spread_v = max(p[1] for p in points) - min(p[1] for p in points)
        along = sorted(p[0] if spread_u >= spread_v else p[1] for p in points)
        gaps = [round(b - a, 4) for a, b in zip(along, along[1:])]
        ok = max(gaps) - min(gaps) <= ABS_TOL_MM
        return ok, f"even spacing along the pattern {gaps}", {"gaps_mm": gaps}

    if form == O.CORNERS:
        span = placement.get("span") or []
        if len(span) != 2 or None in span:
            return False, "no corner span to measure against", {}
        if len(points) != 4:
            return False, f"a corner pattern has four holes, measured {len(points)}", {}
        # Same reasoning as GRID: the plane's basis comes from the geometry, not
        # from the request, so the two spans are matched as a set.
        measured = sorted((max(p[0] for p in points) - min(p[0] for p in points),
                           max(p[1] for p in points) - min(p[1] for p in points)))
        expected = sorted(span)
        ok = all(abs(m - e) <= ABS_TOL_MM for m, e in zip(measured, expected))
        return ok, (
            f"measured corner pattern {measured[0]:.4f} x {measured[1]:.4f} mm "
            f"against {expected[0]:.4f} x {expected[1]:.4f} mm"
        ), {"measured_span_mm": [round(m, 4) for m in measured],
            "expected_span_mm": [round(e, 4) for e in expected]}

    return False, f"no placement rule for {form!r}", {}


# --------------------------------------------------------------------------- #
# the check
# --------------------------------------------------------------------------- #
def _template_features(template: Optional[dict]) -> list[dict]:
    return [f for f in ((template or {}).get("features") or []) if isinstance(f, dict)]


def _represented(obligation: O.Obligation, template: Optional[dict]) -> bool:
    """Does the frozen contract declare anything that could satisfy this?

    Deliberately weak, and reported separately from the geometry: a contract
    that declares a feature is a claim, not evidence. It is worth recording
    because the difference between "the builder never wrote it down" and "the
    builder wrote it down and the kernel did not produce it" points at two
    different bugs.
    """
    if template is None:
        return False
    if obligation.kind in (O.BORE, O.HOLE_PATTERN, O.ROUND):
        # Cylindrical voids in these families are cut in the pad profile, so
        # the evidence in the contract is a hole entry in a sketch profile, not
        # a feature of its own.
        for sketch in (template.get("sketches") or []):
            args = ((sketch or {}).get("profile") or {}).get("args") or {}
            if args.get("holes"):
                return True
        return any(
            f.get("type") in ("Pocket", "Hole", "Groove")
            for f in _template_features(template)
        )
    wanted = obligation.expect_feature or ("Pocket", "Groove")
    return any(
        str(f.get("type", "")).endswith(wanted) for f in _template_features(template)
    )


def _instantiated(topology: Optional[dict]) -> bool:
    return bool(_faces(topology))


def _check_cylindrical(o: O.Obligation, topology: Optional[dict],
                       template: Optional[dict]) -> Fulfillment:
    result = Fulfillment(obligation=o.to_dict())
    result.represented = _represented(o, template)
    result.instantiated = _instantiated(topology)

    if o.radius is None:
        result.status = "warn"
        result.detail = (
            f"{o.label} was requested but no diameter was stated, so nothing "
            "about it can be measured in the built solid"
        )
        return result

    axes = cylinder_axes(topology, o.radius)
    found = len(axes)
    result.evidence = {
        "expected_radius_mm": o.radius,
        "expected_count": o.count,
        "found_axes": found,
        "axes": [[round(c, 4) for c in a.point] for a in axes],
    }
    result.observed = found > 0

    if found == 0:
        radii = cylinder_radii(topology)
        result.evidence["cylindrical_radii_present_mm"] = radii
        result.status = "fail"
        result.detail = (
            f"{o.label}: the request asks for "
            + (f"{o.count} " if o.count else "")
            + f"cylindrical feature(s) of radius {o.radius:g} mm and the built "
            f"solid contains none. "
            + (f"Cylindrical radii present: {radii} mm."
               if radii else "The solid has no cylindrical faces at all.")
        )
        return result

    if o.count is not None and found != o.count:
        result.status = "fail"
        result.detail = (
            f"{o.label}: {o.count} feature(s) of radius {o.radius:g} mm were "
            f"requested and {found} were found in the built solid"
        )
        return result

    if o.placement:
        centre = _body_centre(topology)
        ok, why, evidence = _check_placement(o.placement, axes, centre)
        result.evidence.update(evidence)
        if not ok:
            result.status = "fail"
            result.detail = f"{o.label}: placement does not agree — {why}"
            return result
        result.detail = (
            f"{o.label}: {found} feature(s) of radius {o.radius:g} mm, {why}"
        )
    else:
        result.detail = (
            f"{o.label}: {found} feature(s) of radius {o.radius:g} mm found; "
            "the request fixed no position, so placement was not checked"
        )

    result.verified = True
    result.status = "pass"
    return result


def _check_solid_feature(o: O.Obligation, topology: Optional[dict],
                         template: Optional[dict]) -> Fulfillment:
    """A pocket or a slot: existence is checkable, dimensions are not.

    Reported honestly as such. The omission case — the one this module exists
    for — is still caught, because a feature the builder discarded contributes
    no faces and appears in no feature table.
    """
    result = Fulfillment(obligation=o.to_dict())
    result.represented = _represented(o, template)
    features = (topology or {}).get("features") or {}
    wanted = o.expect_feature or ("Pocket", "Groove")
    cutters = {
        name: entry
        for name, entry in features.items()
        if str(entry.get("type", "")).endswith(wanted)
        and (entry.get("faces") or entry.get("edges"))
    }
    result.instantiated = bool(cutters)
    result.observed = bool(cutters)
    result.evidence = {
        "cutting_features": sorted(cutters),
        "represented_in_contract": result.represented,
    }

    if not result.represented and not result.instantiated:
        result.status = "fail"
        result.detail = (
            f"{o.label} was requested and the built solid contains no "
            + " or ".join(wanted)
            + " feature — it was dropped between the request and the part"
        )
        return result

    if not result.instantiated:
        result.status = "fail"
        result.detail = (
            f"{o.label} is declared in the contract but produced no geometry "
            "in the built solid"
        )
        return result

    result.status = "warn"
    result.detail = (
        f"{o.label} exists in the built solid ({', '.join(sorted(cutters))}), "
        f"but this system cannot independently measure a {o.kind} — it is "
        "present, and its size is not verified"
    )
    return result


def check(obligations: list, topology: Optional[dict],
          template: Optional[dict] = None) -> list[dict]:
    """One fulfillment record per obligation. Deterministic; no model involved.

    ``obligations`` may be ``Obligation`` objects or the dicts a frozen
    Blueprint carries. An empty list returns an empty list — a design that
    obliged nothing is not thereby suspicious.
    """
    items = [o for o in (obligations or []) if o is not None]
    if items and isinstance(items[0], dict):
        items = O.from_dicts(items)
    if not items:
        return []

    if topology is None or not _faces(topology):
        # No evidence is not the same as no feature, and it is not the same as
        # a fulfilled one either. Nothing can be verified, so nothing is.
        return [
            Fulfillment(
                obligation=o.to_dict(),
                status="warn",
                detail=(
                    f"{o.label} was requested and no topology record is "
                    "available for this build, so its presence could not be "
                    "checked against the geometry"
                ),
                evidence={"topology": "absent"},
            ).to_dict()
            for o in items
        ]

    out = []
    for o in items:
        if o.kind in (O.BORE, O.HOLE_PATTERN, O.ROUND):
            # A round leaves cylindrical faces of the requested radius exactly
            # as a hole does, so it is measured rather than merely located.
            out.append(_check_cylindrical(o, topology, template).to_dict())
        else:
            out.append(_check_solid_feature(o, topology, template).to_dict())
    return out


def unfulfilled(rows: Optional[list]) -> list[str]:
    """Obligations the geometry contradicts. The rows that refuse a part."""
    return [r.get("id", "?") for r in (rows or []) if r.get("status") == "fail"]


def unverified(rows: Optional[list]) -> list[str]:
    """Obligations that could not be established either way."""
    return [r.get("id", "?") for r in (rows or []) if r.get("status") == "warn"]
