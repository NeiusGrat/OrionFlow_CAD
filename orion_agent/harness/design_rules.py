"""Deterministic design knowledge: part class, datum convention, material
properties, process constraints and closed-form formulas.

Why this is code and not prompt text
------------------------------------
A weaker model asked to "pick a plane" or "recall 6061 yield strength" will
answer plausibly and sometimes wrongly, and a wrong datum produces geometry
that looks right and measures wrong. Everything here is looked up or computed,
never recalled, so the model's job shrinks to *choosing a class* — which it is
reliable at — while the numbers come from this table.

Nothing here invents dimensions for the user's part. It supplies the standing
engineering facts a draftsman would know without looking up, plus the formulas
that turn a stated dimension into a derived one. Derived values are always
labelled with the formula that produced them so an answer can be audited.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Part classes: how a shape of this kind is actually modelled.
#
# `datum` is the load-bearing field. It fixes the sketch plane, the axis and
# the symmetry so the compiler and the model agree on a convention instead of
# each assuming one. These match freecad/reconstruct.py's placement rules:
#   XY sketch (u,v) -> global (u, v, 0)
#   XZ sketch (u,v) -> global (u, 0, v)      normal -Y
#   YZ sketch (u,v) -> global (0, v, u)      normal -X   <- u is global Z
# --------------------------------------------------------------------------- #

PART_CLASSES: dict[str, dict[str, Any]] = {
    "rotational": {
        "aka": ["shaft", "hub", "flange", "pulley", "bushing", "spacer",
                "collar", "disc", "wheel", "boss", "adapter", "cage"],
        "datum": {
            "sketch_plane": "XZ",
            "axis": "X",
            "symmetry": "axisymmetric about X",
            "coords": "sketch (u,v) = (axial_x, radius)",
            "origin": "mid-plane of the part at x=0 when symmetric, else the "
                      "mounting face",
        },
        "recipe": ["closed profile on XZ", "Revolution 360 about X",
                   "bore/counterbore inside the same profile",
                   "bolt holes as a Pocket from a YZ face sketch"],
        "note": "Keep bore and counterbores in the revolve profile — one "
                "feature, no boolean ordering to get wrong.",
    },
    "plate": {
        "aka": ["plate", "panel", "gasket", "shim", "cover", "blank", "washer"],
        "datum": {
            "sketch_plane": "XY",
            "axis": "Z",
            "symmetry": "none assumed",
            "coords": "sketch (u,v) = (x, y); thickness along +Z",
            "origin": "part centre when symmetric, else lower-left corner",
        },
        "recipe": ["outline on XY", "Pad = thickness",
                   "holes as Pocket through"],
        "note": "State thickness explicitly; it is the one dimension a plate "
                "prompt usually omits.",
    },
    "bracket": {
        "aka": ["bracket", "mount", "angle", "clip", "stand", "support",
                "arm", "lever"],
        "datum": {
            "sketch_plane": "XY",
            "axis": "Z",
            "symmetry": "often mirrored about one plane",
            "coords": "sketch (u,v) = (x, y); base in XY, upright along Z",
            "origin": "the mounting face, so hole depths are measured from it",
        },
        "recipe": ["base outline on XY", "Pad", "upright from a face sketch",
                   "fillet the inside corner", "holes last"],
        "note": "Put the origin on the mounting face — every fit dimension is "
                "referenced from there.",
    },
    "housing": {
        "aka": ["housing", "enclosure", "box", "case", "shell", "cover",
                "chassis", "body"],
        "datum": {
            "sketch_plane": "XY",
            "axis": "Z",
            "symmetry": "usually mirrored about XZ and YZ",
            "coords": "sketch (u,v) = (x, y); height along +Z",
            "origin": "inside floor centre, so wall thickness is symmetric",
        },
        "recipe": ["outer footprint on XY", "Pad to height",
                   "Thickness (shell) to wall", "bosses", "cutouts last"],
        "note": "Shell before adding bosses or the shell will hollow them too.",
    },
    "sheet_metal": {
        "aka": ["sheet metal", "sheet-metal", "bent", "folded", "bend",
                "flange bracket", "stamping"],
        "datum": {
            "sketch_plane": "XY",
            "axis": "Z",
            "symmetry": "flat pattern first",
            "coords": "sketch (u,v) = (x, y); material thickness along +Z",
            "origin": "the fixed face that does not move when bending",
        },
        "recipe": ["flat pattern on XY", "Pad = material thickness",
                   "bends with stated inside radius and K-factor"],
        "note": "Bend radius and K-factor change the flat length — compute "
                "bend allowance, never guess the developed length.",
    },
    "prismatic": {
        "aka": ["block", "body", "manifold", "die", "fixture", "jig", "rail",
                "beam", "bar"],
        "datum": {
            "sketch_plane": "XY",
            "axis": "Z",
            "symmetry": "none assumed",
            "coords": "sketch (u,v) = (x, y); height along +Z",
            "origin": "a corner or the datum face used for machining setup",
        },
        "recipe": ["footprint on XY", "Pad", "pockets and holes from faces"],
        "note": "Machined blocks are datum-driven; pick the setup face as the "
                "origin.",
    },
}

_CLASS_ORDER = ["sheet_metal", "rotational", "housing", "bracket", "plate",
                "prismatic"]

# --------------------------------------------------------------------------- #
# Materials. density g/cm^3, yield MPa, modulus GPa.
# Values are nominal handbook figures for the common temper/grade; they size a
# part, they do not certify one.
# --------------------------------------------------------------------------- #

MATERIALS: dict[str, dict[str, Any]] = {
    "al 6061-t6":  {"density": 2.70, "yield": 276, "modulus": 68.9,
                    "machinability": "excellent", "family": "aluminium",
                    "note": "General structural aluminium; welds well."},
    "al 7075-t6":  {"density": 2.81, "yield": 503, "modulus": 71.7,
                    "machinability": "good", "family": "aluminium",
                    "note": "High strength, poor weldability, stress-corrosion prone."},
    "steel 1018":  {"density": 7.87, "yield": 370, "modulus": 205,
                    "machinability": "good", "family": "carbon steel",
                    "note": "Mild steel, cold drawn; case-harden if wear matters."},
    "steel 4140":  {"density": 7.85, "yield": 655, "modulus": 205,
                    "machinability": "fair", "family": "alloy steel",
                    "note": "Heat-treatable; shafts and highly loaded parts."},
    "ss 304":      {"density": 8.00, "yield": 215, "modulus": 193,
                    "machinability": "fair", "family": "stainless",
                    "note": "Corrosion resistant, work-hardens while machining."},
    "ss 316":      {"density": 8.00, "yield": 205, "modulus": 193,
                    "machinability": "fair", "family": "stainless",
                    "note": "Marine/chemical grade; better pitting resistance than 304."},
    "ti 6al-4v":   {"density": 4.43, "yield": 880, "modulus": 113.8,
                    "machinability": "poor", "family": "titanium",
                    "note": "High strength-to-weight; slow speeds, rigid setups."},
    "brass c360":  {"density": 8.50, "yield": 310, "modulus": 97,
                    "machinability": "excellent", "family": "copper alloy",
                    "note": "Free-machining benchmark material."},
    "abs":         {"density": 1.04, "yield": 40, "modulus": 2.3,
                    "machinability": "n/a", "family": "thermoplastic",
                    "note": "Tough, mouldable; typical FDM/injection choice."},
    "pla":         {"density": 1.24, "yield": 50, "modulus": 3.5,
                    "machinability": "n/a", "family": "thermoplastic",
                    "note": "Stiff but brittle and heat-sensitive; prototypes only."},
    "nylon 66":    {"density": 1.14, "yield": 82, "modulus": 3.0,
                    "machinability": "n/a", "family": "thermoplastic",
                    "note": "Tough and wear resistant; absorbs moisture and grows."},
    "delrin":      {"density": 1.41, "yield": 70, "modulus": 3.1,
                    "machinability": "excellent", "family": "thermoplastic",
                    "note": "POM acetal; dimensionally stable, low friction."},
    "polycarbonate": {"density": 1.20, "yield": 62, "modulus": 2.4,
                      "machinability": "fair", "family": "thermoplastic",
                      "note": "Impact resistant and transparent."},
}

_MATERIAL_ALIASES = {
    "6061": "al 6061-t6", "aluminium": "al 6061-t6", "aluminum": "al 6061-t6",
    "al": "al 6061-t6", "7075": "al 7075-t6",
    "1018": "steel 1018", "mild steel": "steel 1018", "steel": "steel 1018",
    "4140": "steel 4140",
    "304": "ss 304", "316": "ss 316", "stainless": "ss 304",
    "titanium": "ti 6al-4v", "ti": "ti 6al-4v", "6al-4v": "ti 6al-4v",
    "brass": "brass c360",
    "acetal": "delrin", "pom": "delrin", "nylon": "nylon 66",
    "pc": "polycarbonate",
}

# --------------------------------------------------------------------------- #
# Manufacturing processes and the constraints they impose on geometry.
# --------------------------------------------------------------------------- #

PROCESSES: dict[str, dict[str, Any]] = {
    "cnc milling": {
        "min_wall_mm": 0.8, "draft_deg": 0.0,
        "internal_corner_radius_mm": 1.0,
        "tolerance_mm": 0.05,
        "rules": [
            "Every internal vertical corner needs a radius — a square inside "
            "corner cannot be milled. Use >= tool radius (1 mm typical).",
            "Pocket depth beyond ~4x the tool diameter needs a longer tool and "
            "loosens tolerance.",
            "No draft required.",
        ],
    },
    "turning": {
        "min_wall_mm": 0.5, "draft_deg": 0.0,
        "internal_corner_radius_mm": 0.4,
        "tolerance_mm": 0.025,
        "rules": [
            "Part must be axisymmetric — non-round features need a second "
            "milling setup.",
            "Undercuts need a grooving tool; state the groove width.",
        ],
    },
    "injection moulding": {
        "min_wall_mm": 1.0, "draft_deg": 1.5,
        "internal_corner_radius_mm": 0.5,
        "tolerance_mm": 0.1,
        "rules": [
            "Hold wall thickness uniform (1-3 mm). Thick sections sink.",
            "Every face along the pull direction needs 1-2 deg draft.",
            "Rib thickness <= 0.6x the wall it sits on, or it sinks.",
            "Inside corner radius >= 0.5x wall.",
        ],
    },
    "die casting": {
        "min_wall_mm": 1.5, "draft_deg": 2.0,
        "internal_corner_radius_mm": 1.0,
        "tolerance_mm": 0.15,
        "rules": ["Uniform walls 1.5-4 mm.", "Draft 1-3 deg on all pull faces.",
                  "Generous fillets; avoid sharp internal corners."],
    },
    "sand casting": {
        "min_wall_mm": 3.0, "draft_deg": 3.0,
        "internal_corner_radius_mm": 3.0,
        "tolerance_mm": 0.8,
        "rules": ["Walls >= 3-5 mm.", "Draft 2-3 deg.",
                  "Machine allowance 2-3 mm on functional faces."],
    },
    "sheet metal": {
        "min_wall_mm": 0.5, "draft_deg": 0.0,
        "internal_corner_radius_mm": 0.5,
        "tolerance_mm": 0.2,
        "rules": [
            "Inside bend radius >= material thickness.",
            "Hole/slot centre >= 2x thickness from a bend, or it distorts.",
            "Flange length >= 4x thickness to be bendable.",
            "Uniform thickness throughout — it is one sheet.",
        ],
    },
    "fdm 3d printing": {
        "min_wall_mm": 0.8, "draft_deg": 0.0,
        "internal_corner_radius_mm": 0.0,
        "tolerance_mm": 0.2,
        "rules": [
            "Overhangs beyond 45 deg from vertical need support.",
            "Min wall ~0.8 mm (two perimeters at 0.4 nozzle).",
            "Holes print undersize; add ~0.2 mm or ream.",
            "Layer adhesion is the weak axis — orient loads in-plane.",
        ],
    },
    "sls 3d printing": {
        "min_wall_mm": 0.7, "draft_deg": 0.0,
        "internal_corner_radius_mm": 0.0,
        "tolerance_mm": 0.3,
        "rules": ["No supports needed.",
                  "Leave escape holes so trapped powder can drain."],
    },
}

_PROCESS_ALIASES = {
    "cnc": "cnc milling", "milled": "cnc milling", "milling": "cnc milling",
    "machined": "cnc milling", "machining": "cnc milling",
    "turned": "turning", "lathe": "turning", "turning": "turning",
    "injection": "injection moulding", "moulded": "injection moulding",
    "molded": "injection moulding", "injection molding": "injection moulding",
    "die cast": "die casting", "die-cast": "die casting",
    "sand cast": "sand casting", "cast": "sand casting", "casting": "sand casting",
    "sheet metal": "sheet metal", "sheet-metal": "sheet metal",
    "bent": "sheet metal", "laser cut": "sheet metal", "stamped": "sheet metal",
    "3d print": "fdm 3d printing", "3d printed": "fdm 3d printing",
    "fdm": "fdm 3d printing", "printed": "fdm 3d printing",
    "additive": "fdm 3d printing", "sls": "sls 3d printing",
}


# --------------------------------------------------------------------------- #
# Closed-form formulas. Each returns (value, expression) so an answer can cite
# how a derived number was reached.
# --------------------------------------------------------------------------- #

def bolt_circle(pcd_mm: float, count: int, start_deg: float = 0.0
                ) -> tuple[list[tuple[float, float]], str]:
    """Hole centres on a bolt circle. Returns [(u, v)] in the sketch plane."""
    r = pcd_mm / 2.0
    pitch = 360.0 / count
    pts = [(r * math.cos(math.radians(start_deg + i * pitch)),
            r * math.sin(math.radians(start_deg + i * pitch)))
           for i in range(count)]
    return pts, (f"r = PCD/2 = {pcd_mm}/2 = {r:g} mm; "
                 f"pitch = 360/{count} = {pitch:g} deg from {start_deg:g} deg")


def bend_allowance(angle_deg: float, radius_mm: float, thickness_mm: float,
                   k_factor: float = 0.44) -> tuple[float, str]:
    """Developed length added by a bend."""
    ba = math.radians(angle_deg) * (radius_mm + k_factor * thickness_mm)
    return ba, (f"BA = angle_rad x (R + K x t) = {math.radians(angle_deg):.4f} "
                f"x ({radius_mm:g} + {k_factor:g} x {thickness_mm:g}) = {ba:.3f} mm")


def min_hole_edge_distance(hole_d_mm: float, factor: float = 1.5
                           ) -> tuple[float, str]:
    """Centre-to-edge minimum so the wall does not blow out."""
    v = factor * hole_d_mm
    return v, f"edge distance >= {factor:g} x D = {factor:g} x {hole_d_mm:g} = {v:g} mm"


def thread_engagement(nominal_d_mm: float, material_family: str = "aluminium"
                      ) -> tuple[float, str]:
    """Minimum tapped depth for full strength."""
    mult = {"aluminium": 2.0, "thermoplastic": 2.5, "copper alloy": 1.5}.get(
        material_family, 1.0)
    v = mult * nominal_d_mm
    return v, (f"engagement = {mult:g} x D ({material_family}) = "
               f"{mult:g} x {nominal_d_mm:g} = {v:g} mm")


def mass_from_volume(volume_mm3: float, material: str) -> tuple[float, str]:
    """Part mass in grams from solid volume."""
    m = resolve_material(material)
    if not m:
        raise ValueError(f"unknown material: {material!r}")
    rho = m["density"]
    grams = volume_mm3 * rho / 1000.0
    return grams, (f"m = V x rho = {volume_mm3:.1f} mm3 x {rho:g} g/cm3 / 1000 "
                   f"= {grams:.2f} g")


def rib_thickness(wall_mm: float) -> tuple[float, str]:
    v = 0.6 * wall_mm
    return v, f"rib <= 0.6 x wall = 0.6 x {wall_mm:g} = {v:g} mm (avoids sink marks)"


FORMULAS = {
    "bolt_circle": bolt_circle,
    "bend_allowance": bend_allowance,
    "min_hole_edge_distance": min_hole_edge_distance,
    "thread_engagement": thread_engagement,
    "mass_from_volume": mass_from_volume,
    "rib_thickness": rib_thickness,
}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def _norm(text: str) -> str:
    return re.sub(r"[\s_-]+", " ", (text or "").lower()).strip()


def resolve_material(name: str) -> Optional[dict[str, Any]]:
    n = _norm(name)
    if not n:
        return None
    if n in MATERIALS:
        return dict(MATERIALS[n], key=n)
    for alias, key in _MATERIAL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", n):
            return dict(MATERIALS[key], key=key)
    for key in MATERIALS:
        if key in n or n in key:
            return dict(MATERIALS[key], key=key)
    return None


def resolve_process(name: str) -> Optional[dict[str, Any]]:
    n = _norm(name)
    if not n:
        return None
    if n in PROCESSES:
        return dict(PROCESSES[n], key=n)
    for alias, key in _PROCESS_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", n):
            return dict(PROCESSES[key], key=key)
    return None


def classify(text: str, part_hint: str = "") -> tuple[str, str]:
    """Pick a part class from the request. Returns (class, why)."""
    hay = _norm(f"{part_hint} {text}")
    # Sheet metal and rotational have the strongest lexical signals, so they
    # are tested first; 'plate' would otherwise swallow 'bent plate'.
    for cls in _CLASS_ORDER:
        for word in PART_CLASSES[cls]["aka"]:
            if re.search(rf"\b{re.escape(word)}\b", hay):
                return cls, f"matched {word!r}"
    if re.search(r"\b(revolve|revolved|turned|bore|shaft|axis|concentric)\b", hay):
        return "rotational", "rotational language"
    if re.search(r"\bthick(ness)?\b", hay) and re.search(r"\bhole", hay):
        return "plate", "thickness + holes"
    return "prismatic", "no strong signal; defaulted"


@dataclass
class DesignContext:
    """Everything deterministic we know before the model writes a graph."""
    part_class: str = ""
    class_reason: str = ""
    datum: dict[str, Any] = field(default_factory=dict)
    recipe: list[str] = field(default_factory=list)
    class_note: str = ""
    material: dict[str, Any] = field(default_factory=dict)
    process: dict[str, Any] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)
    derived: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        """Compact block for prompt injection."""
        if not self.part_class:
            return ""
        L: list[str] = ["DESIGN CONTEXT (resolved deterministically — use as given):"]
        L.append(f"Part class: {self.part_class} ({self.class_reason})")
        d = self.datum
        if d:
            L.append("Datum / modelling convention:")
            L.append(f"  - sketch plane: {d.get('sketch_plane')}")
            L.append(f"  - axis: {d.get('axis')}")
            L.append(f"  - symmetry: {d.get('symmetry')}")
            L.append(f"  - coords: {d.get('coords')}")
            L.append(f"  - origin: {d.get('origin')}")
        if self.recipe:
            L.append("Feature order: " + " -> ".join(self.recipe))
        if self.class_note:
            L.append(f"Modelling note: {self.class_note}")
        if self.material:
            m = self.material
            L.append(f"Material {m.get('key')}: density {m['density']} g/cm3, "
                     f"yield {m['yield']} MPa, E {m['modulus']} GPa, "
                     f"machinability {m['machinability']}")
            if m.get("note"):
                L.append(f"  note: {m['note']}")
        if self.process:
            p = self.process
            L.append(f"Process {p.get('key')}: min wall {p['min_wall_mm']} mm, "
                     f"draft {p['draft_deg']} deg, internal corner R "
                     f">= {p['internal_corner_radius_mm']} mm, "
                     f"typical tolerance +/-{p['tolerance_mm']} mm")
        if self.checks:
            L.append("Manufacturing rules that constrain this geometry:")
            L += [f"  - {c}" for c in self.checks]
        if self.derived:
            L.append("Derived values (computed, not recalled):")
            L += [f"  - {x['name']} = {x['value']}  [{x['expression']}]"
                  for x in self.derived]
        return "\n".join(L)


def resolve(message: str, part: str = "", material: str = "",
            manufacturing: str = "",
            dimensions: Optional[dict[str, float]] = None,
            counts: Optional[dict[str, int]] = None) -> DesignContext:
    """Build the deterministic context for a request.

    Derived values are only computed from dimensions the caller actually
    stated — this never invents a size for the part.
    """
    cls, why = classify(message, part)
    spec = PART_CLASSES[cls]
    ctx = DesignContext(
        part_class=cls, class_reason=why,
        datum=dict(spec["datum"]), recipe=list(spec["recipe"]),
        class_note=spec["note"],
    )
    m = resolve_material(material) or resolve_material(message)
    if m:
        ctx.material = m
    p = resolve_process(manufacturing) or resolve_process(message)
    if p:
        ctx.process = p
        ctx.checks = list(p["rules"])

    dims = dict(dimensions or {})
    cnts = dict(counts or {})

    # Bolt circle: only when both a circle diameter and a count are stated.
    pcd = next((v for k, v in dims.items()
                if re.search(r"\b(pcd|bcd|bolt.?circle)\b", k, re.I)), None)
    n = next((v for k, v in cnts.items()
              if re.search(r"\b(bolt|hole|spoke|screw)s?\b", k, re.I)), None)
    if pcd and n and n > 0:
        _, expr = bolt_circle(pcd, int(n))
        ctx.derived.append({"name": f"{int(n)} holes on {pcd:g} PCD",
                            "value": "see expression", "expression": expr})

    # Edge distance for a stated hole diameter.
    hd = next((v for k, v in dims.items()
               if re.search(r"\bhole\b.*\b(d|dia|diameter)\b|\bhole_d\b", k, re.I)),
              None)
    if hd:
        v, expr = min_hole_edge_distance(hd)
        ctx.derived.append({"name": "min hole centre-to-edge",
                            "value": f"{v:g} mm", "expression": expr})

    # Thread engagement when a thread is named and the material is known.
    tm = re.search(r"\bM(\d{1,2})\b", message)
    if tm and ctx.material:
        v, expr = thread_engagement(float(tm.group(1)),
                                    ctx.material.get("family", ""))
        ctx.derived.append({"name": f"M{tm.group(1)} min thread engagement",
                            "value": f"{v:g} mm", "expression": expr})

    # Rib thickness follows from a stated wall.
    wall = next((v for k, v in dims.items()
                 if re.search(r"\bwall\b|\bthickness\b", k, re.I)), None)
    if wall and ctx.process and ctx.process.get("key") in (
            "injection moulding", "die casting"):
        v, expr = rib_thickness(wall)
        ctx.derived.append({"name": "max rib thickness",
                            "value": f"{v:g} mm", "expression": expr})

    # Wall vs process minimum — a real violation, worth surfacing.
    if wall and ctx.process and wall < ctx.process["min_wall_mm"]:
        ctx.checks.append(
            f"VIOLATION: stated wall {wall:g} mm is below the "
            f"{ctx.process['key']} minimum of {ctx.process['min_wall_mm']} mm.")
    return ctx
