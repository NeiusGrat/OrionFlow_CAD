"""Deterministic engineering arithmetic. No model ever runs any of this.

The rule this module enforces is not stylistic. The adapter's own model card
records the limitation plainly: it *"derives volumes correctly symbolically but
does not evaluate them — a stated numeric volume in its reasoning should be
recomputed from its expression, not trusted."* Every held-out failure of the
``assert`` class is a case where the symbolic derivation and the solid
disagreed, and no amount of re-prompting recovered one. Arithmetic belongs in
Python, where it is exact and checkable, and the model's job is to decide *which*
formula applies — which is the part it is actually good at.

Two kinds of thing live here:

* :func:`check_stated_volume` — the cheapest guard in the system. The model
  writes a number in its ``<think>`` block and an expression in its ``body``
  assertion. Those are two independent claims about the same quantity, and they
  can be compared before a kernel is ever started. A mismatch means the prose is
  lying about the contract even when the contract itself is right.
* Closed-form engineering: bearing life, beam bending, thread engagement,
  thermal growth, mass properties, Pappus. Existing calculators scattered across
  :mod:`orion.families` and :mod:`orion.ekg` are re-exported so there is one
  place to look and one registry to expose as tools.

Every function returns a dict with its inputs echoed back, so a result is
self-describing in a trajectory log and can be quoted without re-deriving it.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

from . import expr as E

# --------------------------------------------------------------------------- #
# the model's own claim, checked
# --------------------------------------------------------------------------- #
#: "Predicted volume: 259468.9009 mm^3" — the line pack_sft asks the model to
#: end its derivation with. Tolerant of unit spelling and spacing because this
#: reads *generated* text, not authored text.
_STATED_VOLUME = re.compile(
    r"predicted\s+volume\s*[:=]\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", re.I)


def check_stated_volume(payload: dict, thinking: str,
                        tol_rel: float = 1e-6) -> dict:
    """Compare the volume the model *wrote* against the volume it *derived*.

    ``payload`` is a parsed Blueprint; ``thinking`` is the text of its think
    block. The Blueprint's ``body`` assertion carries a closed-form expression
    over the named variables — that is the contract the kernel will be held to.
    The think block carries a number the model computed in its head. Evaluating
    the expression settles which one to believe, and costs microseconds against
    a build that costs seconds.

    A mismatch does not by itself mean the part is wrong: the expression is what
    gets verified, so a part with bad prose can still build and pass. It means
    the *explanation* is wrong, which matters because the explanation is what a
    user reads and what a repair turn reasons from.
    """
    out: dict[str, Any] = {"checked": False, "stated": None, "derived": None,
                           "rel_err": None, "agrees": None, "why": ""}

    m = _STATED_VOLUME.search(thinking or "")
    if not m:
        out["why"] = "no 'Predicted volume:' line in the derivation"
        return out
    out["stated"] = float(m.group(1))

    body = next((a for a in (payload.get("assertions") or [])
                 if a.get("id") == "body"), None)
    if body is None:
        out["why"] = "no 'body' assertion to derive from"
        return out
    if body.get("kind") != "body_volume":
        # A mesh-converged or profile-area body has no closed form to evaluate;
        # that is a legitimate design, not a defect.
        out["why"] = f"body assertion is {body.get('kind')!r}, not a closed form"
        return out

    try:
        out["derived"] = E.evaluate(body.get("target"),
                                    payload.get("variables") or {})
    except (E.ExprError, TypeError, ValueError) as exc:
        out["why"] = f"body expression did not evaluate: {exc}"
        return out

    denom = max(abs(out["derived"]), 1e-12)
    out["rel_err"] = abs(out["stated"] - out["derived"]) / denom
    out["agrees"] = out["rel_err"] <= tol_rel
    out["checked"] = True
    out["why"] = ("stated volume matches the derivation" if out["agrees"] else
                  f"the derivation evaluates to {out['derived']:.4f} mm^3 but "
                  f"the reasoning states {out['stated']:.4f} — the expression "
                  f"is the contract, so the stated number is what is wrong")
    return out


# --------------------------------------------------------------------------- #
# materials — nominal handbook values, room temperature
# --------------------------------------------------------------------------- #
#: density kg/m^3, E MPa, yield MPa, alpha 1e-6/K. Nominal wrought values for
#: sizing and mass estimates; a real stress case wants the supplier's cert, not
#: this table, and callers should say so when they quote from it.
MATERIALS: dict[str, dict[str, float]] = {
    "aluminium_6061_t6": {"density": 2700.0, "E": 68900.0, "yield": 276.0,
                          "alpha": 23.6},
    "aluminium_7075_t6": {"density": 2810.0, "E": 71700.0, "yield": 503.0,
                          "alpha": 23.4},
    "steel_1018":        {"density": 7870.0, "E": 205000.0, "yield": 370.0,
                          "alpha": 11.9},
    "steel_4140":        {"density": 7850.0, "E": 205000.0, "yield": 655.0,
                          "alpha": 12.3},
    "stainless_304":     {"density": 8000.0, "E": 193000.0, "yield": 215.0,
                          "alpha": 17.3},
    "titanium_ti6al4v":  {"density": 4430.0, "E": 113800.0, "yield": 880.0,
                          "alpha": 8.6},
    "brass_c360":        {"density": 8500.0, "E": 97000.0, "yield": 310.0,
                          "alpha": 20.5},
    "abs":               {"density": 1040.0, "E": 2200.0, "yield": 40.0,
                          "alpha": 90.0},
    "pla":               {"density": 1240.0, "E": 3500.0, "yield": 50.0,
                          "alpha": 68.0},
    "nylon_pa12":        {"density": 1010.0, "E": 1700.0, "yield": 48.0,
                          "alpha": 110.0},
}


def material(name: str) -> dict:
    """Look a material up, or raise with the list of what is known."""
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    if key not in MATERIALS:
        raise KeyError(f"unknown material {name!r}; known: "
                       f"{', '.join(sorted(MATERIALS))}")
    return {"material": key, **MATERIALS[key]}


def mass_properties(volume_mm3: float, material_name: str) -> dict:
    """Mass from a measured volume. Volume comes from the kernel, never a model."""
    m = material(material_name)
    kg = volume_mm3 * 1e-9 * m["density"]
    return {"volume_mm3": volume_mm3, "material": m["material"],
            "density_kg_m3": m["density"], "mass_kg": kg,
            "mass_g": kg * 1000.0, "weight_n": kg * 9.80665}


def centre_of_mass(parts: list[dict]) -> dict:
    """Composite centroid of ``[{volume_mm3, x, y, z}, ...]``.

    Uniform density per part is assumed unless a part carries ``density``; a
    hollow or multi-material assembly must pass it explicitly rather than let
    this guess.
    """
    tot = 0.0
    acc = [0.0, 0.0, 0.0]
    for p in parts:
        w = float(p["volume_mm3"]) * float(p.get("density", 1.0))
        tot += w
        for i, axis in enumerate("xyz"):
            acc[i] += w * float(p.get(axis, 0.0))
    if tot <= 0:
        raise ValueError("total weighted volume is zero")
    return {"n_parts": len(parts), "total_volume_mm3":
            sum(float(p["volume_mm3"]) for p in parts),
            "cx": acc[0] / tot, "cy": acc[1] / tot, "cz": acc[2] / tot}


def pappus_revolution(area_mm2: float, centroid_r_mm: float,
                      angle_deg: float = 360.0) -> dict:
    """Pappus's second theorem: V = theta * R_centroid * A.

    Exact for any profile revolved about an axis it does not cross — which is
    why a revolved feature's volume never needs a mesh to predict.
    """
    if centroid_r_mm <= 0:
        raise ValueError("centroid radius must be positive (profile must not "
                         "cross the axis)")
    theta = math.radians(angle_deg)
    return {"area_mm2": area_mm2, "centroid_r_mm": centroid_r_mm,
            "angle_deg": angle_deg, "volume_mm3": theta * centroid_r_mm * area_mm2}


# --------------------------------------------------------------------------- #
# structural
# --------------------------------------------------------------------------- #
def beam_bending(load_n: float, length_mm: float, width_mm: float,
                 height_mm: float, material_name: str,
                 case: str = "cantilever_end") -> dict:
    """Stress and deflection of a rectangular beam.

    ``case`` is ``cantilever_end`` (fixed one end, load at the tip) or
    ``simply_supported_centre``. Second moment I = b*h^3/12 about the neutral
    axis, so height dominates cubically — the single most useful fact when a
    rib is being sized.
    """
    mat = material(material_name)
    inertia = width_mm * height_mm ** 3 / 12.0
    c = height_mm / 2.0
    if case == "cantilever_end":
        moment = load_n * length_mm
        defl = load_n * length_mm ** 3 / (3.0 * mat["E"] * inertia)
    elif case == "simply_supported_centre":
        moment = load_n * length_mm / 4.0
        defl = load_n * length_mm ** 3 / (48.0 * mat["E"] * inertia)
    else:
        raise ValueError("case must be cantilever_end or "
                         "simply_supported_centre")
    stress = moment * c / inertia
    return {"case": case, "load_n": load_n, "length_mm": length_mm,
            "width_mm": width_mm, "height_mm": height_mm,
            "material": mat["material"], "I_mm4": inertia,
            "moment_nmm": moment, "max_stress_mpa": stress,
            "deflection_mm": defl, "yield_mpa": mat["yield"],
            "safety_factor": (mat["yield"] / stress) if stress > 0 else
            float("inf")}


def thermal_expansion(length_mm: float, delta_t_c: float,
                      material_name: str) -> dict:
    """dL = alpha * L * dT. The reason a press fit at 20 C is a slip fit at 120."""
    mat = material(material_name)
    dl = mat["alpha"] * 1e-6 * length_mm * delta_t_c
    return {"length_mm": length_mm, "delta_t_c": delta_t_c,
            "material": mat["material"], "alpha_1e6_per_k": mat["alpha"],
            "delta_mm": dl, "final_mm": length_mm + dl}


def bearing_life_l10(dynamic_c_n: float, load_p_n: float, speed_rpm: float,
                     rolling_element: str = "ball") -> dict:
    """ISO 281 basic rating life. L10 = (C/P)^p million revolutions.

    p = 3 for ball bearings, 10/3 for roller. The cube law is the point: halving
    the load multiplies life by eight, which is usually a cheaper fix than a
    bigger bearing.
    """
    if load_p_n <= 0:
        raise ValueError("equivalent dynamic load must be positive")
    p = 3.0 if rolling_element == "ball" else 10.0 / 3.0
    l10_mrev = (dynamic_c_n / load_p_n) ** p
    hours = (l10_mrev * 1e6) / (60.0 * speed_rpm) if speed_rpm > 0 else \
        float("inf")
    return {"dynamic_c_n": dynamic_c_n, "load_p_n": load_p_n,
            "speed_rpm": speed_rpm, "rolling_element": rolling_element,
            "exponent": p, "l10_million_rev": l10_mrev, "l10_hours": hours}


def tensile_stress_area(d_mm: float, pitch_mm: float) -> float:
    """ISO 898-1 tensile stress area: A_t = (pi/4)(d - 0.9382 p)^2."""
    return math.pi / 4.0 * (d_mm - 0.9382 * pitch_mm) ** 2


def thread_engagement(d_mm: float, pitch_mm: float, bolt_uts_mpa: float,
                      nut_material: str) -> dict:
    """Engagement length at which the tapped thread carries the bolt's tension.

    Force balance, not a rule of thumb: the bolt fails in tension at
    ``A_t * UTS``; the internal thread strips over a cylindrical shear area
    ``pi * d * Le``, of which roughly half is thread flank rather than air. Set
    the two equal and solve for ``Le``. Shear yield is taken as 0.577 * tensile
    yield (von Mises).

    This is why a steel bolt into aluminium needs about twice the engagement of
    the same bolt into steel — the formula produces that, rather than asserting
    it.
    """
    mat = material(nut_material)
    at = tensile_stress_area(d_mm, pitch_mm)
    tau_allow = 0.577 * mat["yield"]
    le = (at * bolt_uts_mpa) / (0.5 * math.pi * d_mm * tau_allow)
    return {"d_mm": d_mm, "pitch_mm": pitch_mm,
            "tensile_stress_area_mm2": at, "bolt_uts_mpa": bolt_uts_mpa,
            "nut_material": mat["material"], "shear_allow_mpa": tau_allow,
            "min_engagement_mm": le, "engagement_diameters": le / d_mm}


# --------------------------------------------------------------------------- #
# re-exports — one registry, so nothing has to know where a formula lives
# --------------------------------------------------------------------------- #
# Imported directly, not behind a lazy wrapper: anything that introspects this
# registry to build a tool surface reads the real signature, and a ``*args,
# **kwargs`` shim would advertise ``args``/``kwargs`` as the parameters to pass.
from .ekg import kutzbach_mobility                            # noqa: E402
from .families import (                                       # noqa: E402
    bolt_torque_nm,
    key_capacity,
    key_for_shaft,
    screw_kinematics,
    spring_mechanics,
)


def gear_ratio(z_driver: int, z_driven: int, module_mm: Optional[float] = None
               ) -> dict:
    """Speed ratio and, given a module, the standard centre distance."""
    if z_driver <= 0 or z_driven <= 0:
        raise ValueError("tooth counts must be positive")
    out = {"z_driver": z_driver, "z_driven": z_driven,
           "ratio": z_driven / z_driver,
           "reduction": f"{z_driven / z_driver:.4g}:1"}
    if module_mm:
        out["module_mm"] = module_mm
        out["centre_distance_mm"] = module_mm * (z_driver + z_driven) / 2.0
    return out


#: Every calculator, by name. Exposed as one dict so the orchestration layer can
#: publish it as a tool surface without importing six modules — and so that
#: "which calculations exist" has exactly one answer.
CALCULATORS = {
    "check_stated_volume": check_stated_volume,
    "mass_properties": mass_properties,
    "centre_of_mass": centre_of_mass,
    "pappus_revolution": pappus_revolution,
    "beam_bending": beam_bending,
    "thermal_expansion": thermal_expansion,
    "bearing_life_l10": bearing_life_l10,
    "thread_engagement": thread_engagement,
    "tensile_stress_area": tensile_stress_area,
    "gear_ratio": gear_ratio,
    "bolt_torque_nm": bolt_torque_nm,
    "screw_kinematics": screw_kinematics,
    "spring_mechanics": spring_mechanics,
    "key_capacity": key_capacity,
    "key_for_shaft": key_for_shaft,
    "kutzbach_mobility": kutzbach_mobility,
    "material": material,
}


def run(name: str, **kwargs) -> dict:
    """Dispatch by name. Unknown names list what is available rather than
    raising something the caller has to guess at."""
    fn = CALCULATORS.get(name)
    if fn is None:
        raise KeyError(f"unknown calculator {name!r}; known: "
                       f"{', '.join(sorted(CALCULATORS))}")
    result = fn(**kwargs)
    return result if isinstance(result, dict) else {"value": result}
