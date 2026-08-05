"""The calculators, run against the part that was actually built.

Until now :mod:`orion.calc` was unreachable from the live build path. The
reasoning chain *names* the arithmetic that ought to decide a design, the
calculators exist and are correct, and nothing ever ran one against a finished
solid. So VERIFIED meant "the geometry matches the closed form the model
authored" — a true statement about shape that says nothing about whether the
part survives its duty.

This module closes that. A Blueprint may declare an ``engineering`` block in its
``design_plan``::

    "design_plan": {
      "engineering": {
        "material": "aluminium_6061_t6",
        "checks": [
          {"id": "arm_stress",
           "calc": "beam_bending",
           "args": {"load_n": 196.0, "length_mm": "=arm", "width_mm": "=w",
                    "height_mm": "=t", "material_name": "@material"},
           "expect": {"safety_factor": {"min": 1.5}}}
        ]
      }
    }

and every declared check runs after the build, against the measured solid.

**Inputs are derived, never authored twice.** An argument is one of:

``12.5``        a number, used as written
``"=w*2"``      an expression over the Blueprint's own frozen variables
``"@volume"``   a quantity the kernel measured
``"cantilever"``  anything else is a literal string (a case name, a material)

The ``=`` form is the important one. A load has to be stated — it is a fact
about the world, not about the part — but every *dimension* fed to a calculator
must come from the same frozen variables the geometry was built from. Otherwise
the model could author a beam 8 mm thick, check the stress on a 20 mm one, and
both numbers would be internally consistent.

**Nothing is assumed.** No material is guessed, no load is invented, and a
design that declares nothing gets no engineering checks and is completely
unaffected — which is every Blueprint in the existing corpus.

**A declared check that cannot run is a failure, not a silence.** Once a design
says "this must hold", being unable to evaluate it is a defect in the design.
That is the opposite of the rule for things nobody claimed, which are simply
absent.
"""

from __future__ import annotations

from typing import Any, Optional

from . import calc, expr as E

#: Arguments that name a thing rather than measure one, so a bare string is a
#: literal and not an expression to evaluate.
_REF = "@"
_EXPR = "="


class EngineeringError(ValueError):
    """A declaration that cannot be understood."""


def block_of(blueprint_dict: dict) -> dict:
    """The ``engineering`` block, or an empty one. Never raises."""
    plan = blueprint_dict.get("design_plan") or {}
    block = plan.get("engineering") or {}
    return block if isinstance(block, dict) else {}


def _context(measured: Optional[dict], material: Optional[str]) -> dict:
    """What ``@`` references can resolve to.

    Only quantities the kernel actually reported, plus the declared material.
    A reference to something unmeasured resolves to nothing and fails the check
    that asked for it, rather than defaulting to zero — a stress computed on a
    silently-zero dimension is worse than no stress at all.
    """
    m = measured or {}
    ctx: dict[str, Any] = {}
    if m.get("body_volume") is not None:
        ctx["volume"] = float(m["body_volume"])
    bbox = m.get("bbox")
    if bbox and len(bbox) == 6:
        ctx["bbox_x"] = bbox[3] - bbox[0]
        ctx["bbox_y"] = bbox[4] - bbox[1]
        ctx["bbox_z"] = bbox[5] - bbox[2]
    if material:
        ctx["material"] = material
    return ctx


def _resolve(value: Any, variables: dict, ctx: dict) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return value
    if value.startswith(_EXPR):
        return E.evaluate(value[1:], variables)
    if value.startswith(_REF):
        key = value[1:]
        if key not in ctx:
            raise EngineeringError(
                f"{value!r} is not available — the kernel reported no {key}")
        return ctx[key]
    return value


def _grade(result: dict, expect: dict) -> tuple[bool, list[str]]:
    """Compare named outputs against declared bounds."""
    ok, notes = True, []
    for field, bound in (expect or {}).items():
        if field not in result:
            ok = False
            notes.append(f"{field} is not one of this calculator's outputs "
                         f"({', '.join(sorted(result))})")
            continue
        got = result[field]
        if not isinstance(got, (int, float)) or isinstance(got, bool):
            ok = False
            notes.append(f"{field} is {got!r}, which is not a number")
            continue
        if not isinstance(bound, dict):
            bound = {"min": bound}
        if "min" in bound and got < float(bound["min"]):
            ok = False
            notes.append(f"{field} {got:.4g} is below the required minimum "
                         f"{float(bound['min']):.4g}")
        if "max" in bound and got > float(bound["max"]):
            ok = False
            notes.append(f"{field} {got:.4g} exceeds the allowed maximum "
                         f"{float(bound['max']):.4g}")
        if ok and not notes:
            notes.append(f"{field} = {got:.4g}")
    return ok, notes


def run_checks(blueprint_dict: dict, variables: dict,
               measured: Optional[dict] = None) -> list[dict]:
    """Every declared engineering check, run. Neutral rows, no verdict shape.

    Each row: ``{id, label, calc, passed, detail, result, expect}``. ``passed``
    is ``None`` when the calculator ran but the design declared no bound to hold
    it to — that is an observation, and the caller must not tick it green.
    """
    block = block_of(blueprint_dict)
    declared = block.get("checks") or []
    if not isinstance(declared, list):
        return []

    material = block.get("material")
    ctx = _context(measured, material)
    rows: list[dict] = []

    for i, spec in enumerate(declared):
        if not isinstance(spec, dict):
            continue
        name = spec.get("calc") or ""
        cid = spec.get("id") or f"{name or 'check'}{i}"
        expect = spec.get("expect") or {}
        label = spec.get("label") or _label_for(name, cid)
        row = {"id": cid, "label": label, "calc": name,
               "passed": False, "detail": "", "result": {}, "expect": expect}

        if name not in calc.CALCULATORS:
            row["detail"] = (f"no calculator named {name!r}; known: "
                             f"{', '.join(sorted(calc.CALCULATORS))}")
            rows.append(row)
            continue

        try:
            args = {k: _resolve(v, variables, ctx)
                    for k, v in (spec.get("args") or {}).items()}
        except (EngineeringError, E.ExprError, TypeError, ValueError) as exc:
            row["detail"] = f"could not resolve arguments: {exc}"
            rows.append(row)
            continue

        try:
            result = calc.run(name, **args)
        except Exception as exc:  # noqa: BLE001 - any calculator failure is the check failing
            row["detail"] = f"{name} could not be evaluated: {exc}"
            rows.append(row)
            continue

        row["result"] = {k: v for k, v in result.items()
                         if isinstance(v, (int, float, str))}
        if not expect:
            # Ran, but the design named no bound. Reported, never ticked.
            row["passed"] = None
            row["detail"] = _summarise(result)
            rows.append(row)
            continue

        ok, notes = _grade(result, expect)
        row["passed"] = ok
        row["detail"] = "; ".join(notes) or _summarise(result)
        rows.append(row)

    return rows


def observations(blueprint_dict: dict, measured: Optional[dict] = None) -> dict:
    """Engineering quantities derivable without anything being declared.

    Only mass, and only when a material is named: the volume is the kernel's and
    the density is a table lookup, so the number is exact given the material.
    Without a declared material there is nothing honest to report — density is
    not guessable from a shape.
    """
    block = block_of(blueprint_dict)
    material = block.get("material")
    volume = (measured or {}).get("body_volume")
    if not material or volume is None:
        return {}
    try:
        m = calc.mass_properties(float(volume), material)
    except (KeyError, TypeError, ValueError):
        return {}
    return {"material": m["material"], "mass_g": round(m["mass_g"], 3)}


_LABELS = {
    "beam_bending": "Beam stress within yield",
    "mass_properties": "Mass within budget",
    "thermal_expansion": "Thermal growth within allowance",
    "bearing_life_l10": "Bearing life meets duty",
    "thread_engagement": "Thread engagement sufficient",
    "gear_ratio": "Gear ratio as specified",
    "spring_mechanics": "Spring within working range",
    "key_capacity": "Key transmits the torque",
    "bolt_torque_nm": "Bolt torque as specified",
}


def _label_for(name: str, cid: str) -> str:
    return _LABELS.get(name, f"Engineering check {cid}")


def _summarise(result: dict) -> str:
    """A one-line reading of a calculator's output, for an ungraded run."""
    parts = [f"{k}={v:.4g}" for k, v in result.items()
             if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return ", ".join(parts[:4]) or "ran"
