"""Hole groups: a face, a diameter, a count and a placement.

The defect this exists for. ``l_bracket`` carried one ``hole_d`` slot, shared
between the motor pattern on the upright and the mounting pattern through the
base. A NEMA 17 bracket has both, at Ø3.5 and Ø6.5, and one slot cannot hold
two numbers — so the request either lost the second diameter entirely or
silently cut the base holes at the upright's size. Both happened, from the same
cause: a part may have any number of hole groups and the schema could name one.

A group is therefore a *structure*, not a set of flat slots:

    {face, diameter, count, placement, ...placement parameters}

and a part carries a list of them. Adding a third pattern is another entry, not
another pair of slots named after where it goes.

**The capability map is explicit.** :data:`FACES` says which faces a family
actually has and what frame each is drawn in; :data:`PLACEMENTS` says how holes
may be arranged on one. A group naming a face or a placement that is not there
is reported by name — "this family has no `web` face" — and never quietly
dropped, which is the failure this module was written after.

**Placement is arithmetic, not a template.** Each placement turns its own
parameters into coordinates in the face's frame, and every coordinate is an
expression over the Blueprint's own variables so the pattern stays parametric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class HoleError(ValueError):
    """A group that cannot be placed, named so the caller can say why."""


@dataclass(frozen=True)
class Face:
    """One drillable face, in the frame its sketch is actually drawn in.

    ``u_origin`` is not always zero: ``l_bracket`` draws both its base and its
    upright centred on ``extent/2`` so the inside corner sits at the origin, and
    a placement that assumed a centred frame would put every hole half a plate
    out. The frame is data here so that cannot be assumed.
    """

    name: str
    u_origin: str
    u_extent: str
    v_extent: str
    depth: str
    #: What the two axes mean to a person, for error messages that name the
    #: dimension the user typed rather than a letter.
    u_label: str = "length"
    v_label: str = "width"


#: Which faces each family exposes. A family absent from here has no hole-group
#: support yet, which is a different fact from a family whose faces reject the
#: group — and the caller reports them differently.
FACES: dict[str, dict[str, Face]] = {
    "l_bracket": {
        "base": Face("base", "BL/2", "BL", "BW", "BT",
                     "base length", "base width"),
        "upright": Face("upright", "UH/2", "UH", "UW", "UT",
                        "upright height", "upright width"),
    },
    "rect_plate": {
        "top": Face("top", "0*L", "L", "W", "T", "length", "width"),
    },
}

#: How holes may be arranged on a face, and what each arrangement needs.
PLACEMENTS: dict[str, tuple[str, ...]] = {
    "square": ("pitch",),
    "grid": ("pitch_u", "pitch_v"),
    "corners": ("edge_gap",),
    "bolt_circle": ("pcd",),
}


@dataclass
class Group:
    """One hole pattern on one face."""

    id: str
    face: str
    radius: float
    placement: str
    params: dict = field(default_factory=dict)
    #: Prefix for the variables this group introduces. Empty keeps the historic
    #: names (``hole_r``, ``bolt_half``) so a bracket that was expressible
    #: before hashes exactly as it did.
    prefix: str = ""

    @property
    def r_var(self) -> str:
        return f"{self.prefix}hole_r"


def _n(params: dict, key: str) -> Optional[float]:
    value = params.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def count_of(group: Group) -> int:
    """How many holes this group places. Known before any geometry exists."""
    if group.placement in ("square", "corners"):
        return 4
    if group.placement == "grid":
        return (2 if _n(group.params, "pitch_u") else 1) * \
               (2 if _n(group.params, "pitch_v") else 1)
    if group.placement == "bolt_circle":
        return int(group.params.get("count") or 0)
    raise HoleError(f"unknown placement {group.placement!r}")


def coordinates(group: Group, face: Face, v: dict,
                numbers: dict) -> list[list[str]]:
    """``[[u_expr, v_expr, r_expr], ...]`` in the face's own frame.

    Writes the variables the expressions reference into ``v`` — the coordinates
    stay parametric, so a pattern re-solves when its pitch is edited rather than
    freezing into literals.
    """
    r = group.radius
    rv = group.r_var
    v[rv] = r
    u0 = face.u_origin
    p = group.params
    out: list[list[str]] = []

    if group.placement == "square":
        pitch = _n(p, "pitch")
        if not pitch:
            raise HoleError("a square bolt pattern needs its spacing")
        half = f"{group.prefix}half"
        v[half] = pitch / 2.0
        for su in ("-", "+"):
            for sv in ("-", "+"):
                out.append([f"{u0} {su} {half}", f"0 {sv} {half}", rv])

    elif group.placement == "grid":
        pu, pv = _n(p, "pitch_u"), _n(p, "pitch_v")
        if not (pu or pv):
            raise HoleError("a grid needs a spacing along at least one axis")
        us, vs = [u0], ["0*" + rv]
        if pu:
            hu = f"{group.prefix}half_u"
            v[hu] = pu / 2.0
            us = [f"{u0} - {hu}", f"{u0} + {hu}"]
        if pv:
            hv = f"{group.prefix}half_v"
            v[hv] = pv / 2.0
            vs = [f"-{hv}", f"+{hv}"]
        for uu in us:
            for vv in vs:
                out.append([uu, vv, rv])

    elif group.placement == "corners":
        gap = _n(p, "edge_gap")
        if not gap:
            raise HoleError(
                "corner holes need a distance in from the edge — "
                '"near each corner" does not fix a position')
        gv = f"{group.prefix}gap"
        v[gv] = gap
        for su in ("-", "+"):
            for sv in ("-", "+"):
                out.append([f"{u0} {su} ({face.u_extent}/2 - {gv})",
                            f"{sv} ({face.v_extent}/2 - {gv})", rv])

    elif group.placement == "bolt_circle":
        import math

        pcd = _n(p, "pcd")
        n = count_of(group)
        if not pcd or n < 1:
            raise HoleError("a bolt circle needs a diameter and a count")
        pv = f"{group.prefix}pcd_r"
        v[pv] = pcd / 2.0
        for i in range(n):
            a = 2 * math.pi * i / n
            out.append([f"{u0} + {pv}*{math.cos(a):.10f}",
                        f"{pv}*{math.sin(a):.10f}", rv])
    else:
        raise HoleError(f"unknown placement {group.placement!r}")
    return out


def validate(group: Group, face: Face, numbers: dict) -> None:
    """Refuse a group that does not fit, naming the number that is wrong.

    ``numbers`` are the family's resolved dimensions, so the checks are against
    the plate this pattern is actually going on rather than against a rule of
    thumb.
    """
    r = group.radius
    if r <= 0:
        raise HoleError("hole radius must be positive")
    u_ext = numbers.get(face.u_extent)
    v_ext = numbers.get(face.v_extent)
    p = group.params

    if group.placement == "square":
        half = (_n(p, "pitch") or 0.0) / 2.0
        if v_ext and half + r >= v_ext / 2.0:
            raise HoleError(
                f"a {_n(p, 'pitch'):g} mm bolt square is wider than the "
                f"{v_ext:g} mm {face.v_label}")
    elif group.placement == "corners":
        gap = _n(p, "edge_gap") or 0.0
        if gap <= r:
            raise HoleError(
                f"holes {2 * r:g} mm across cannot sit {gap:g} mm from the "
                f"corner without breaking the edge")
        if u_ext and v_ext and (gap + r >= min(u_ext, v_ext) / 2.0):
            raise HoleError(
                f"corner holes {gap:g} mm in overlap at the centre of a "
                f"{u_ext:g} x {v_ext:g} mm face")
    elif group.placement == "grid":
        for key, ext, label in (("pitch_u", u_ext, face.u_label),
                                ("pitch_v", v_ext, face.v_label)):
            pitch = _n(p, key)
            if pitch and ext and pitch / 2.0 + r >= ext / 2.0:
                raise HoleError(
                    f"a {pitch:g} mm pitch runs off the {ext:g} mm {label}")
    elif group.placement == "bolt_circle":
        pcd = _n(p, "pcd") or 0.0
        if v_ext and pcd / 2.0 + r >= v_ext / 2.0:
            raise HoleError(
                f"a {pcd:g} mm bolt circle does not fit the {v_ext:g} mm "
                f"{face.v_label}")


def volume_term(group: Group, face: Face) -> str:
    """What this group removes, exactly: n cylinders of the face's depth."""
    return f"{count_of(group)}*pi*{group.r_var}**2*{face.depth}"


def obligation(group: Group) -> dict:
    """What the built solid is now obliged to contain, per group.

    One per group rather than one per part: a bracket with a Ø3.5 pattern and a
    Ø6.5 pattern that came out with eight Ø3.5 holes satisfies "eight holes"
    and is the wrong part.
    """
    return {
        "id": group.id,
        "kind": "hole_pattern",
        "count": count_of(group),
        "diameter": round(group.radius * 2, 6),
        "face": group.face,
        "source": "hole group",
    }


def capability(family: str, face: str, placement: str) -> Optional[str]:
    """``None`` when this family can place that group, else why it cannot.

    Named rather than boolean so the caller can report the missing capability
    verbatim instead of "unsupported".
    """
    faces = FACES.get(family)
    if faces is None:
        return (f"{family} has no drillable faces declared, so a hole group "
                f"cannot be placed on it")
    if face not in faces:
        return (f"{family} has no {face!r} face — it has "
                f"{', '.join(sorted(faces))}")
    if placement not in PLACEMENTS:
        return (f"{placement!r} is not a hole placement here — known: "
                f"{', '.join(sorted(PLACEMENTS))}")
    return None


def from_eds(family: str, raw: Any) -> tuple[list[Group], list[dict]]:
    """Model-supplied hole groups -> ``(groups, unsupported)``.

    Every entry is either compiled or reported. Nothing is dropped: an entry
    naming a face this family does not have travels into the frozen contract as
    an explicit missing-capability record, because "we cannot do that" and "we
    did not notice" are different facts and used to look identical.
    """
    groups: list[Group] = []
    unsupported: list[dict] = []
    if not isinstance(raw, list):
        return groups, unsupported

    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        face = str(entry.get("face") or "").strip().lower()
        placement = str(entry.get("placement") or "").strip().lower()
        d = entry.get("diameter")
        gid = str(entry.get("id") or f"{face or 'hole'}_group_{i + 1}")
        why = capability(family, face, placement)
        if why is None and not isinstance(d, (int, float)):
            why = "no diameter was given for this hole group"
        if why is not None:
            unsupported.append({
                "feature": gid,
                "requested": entry,
                "source": "hole group",
                "reason": why,
            })
            continue
        params = {k: v for k, v in entry.items()
                  if k in ("pitch", "pitch_u", "pitch_v", "edge_gap", "pcd",
                           "count")}
        groups.append(Group(id=gid, face=face, radius=float(d) / 2.0,
                            placement=placement, params=params,
                            prefix=f"g{i + 1}_"))
    return groups, unsupported
