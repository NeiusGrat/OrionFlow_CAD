"""design_reasoning — the "mechanical engineer reasoning" layer.

Produces a structured design plan BEFORE any CAD code is written, grounded in
the knowledge base: sourced-part dimensions are injected as hard facts the
model must respect. Falls back to a deterministic plan when no LLM is
available (tests, offline runs), so the harness never depends on network.
"""

from __future__ import annotations

import json
import logging
import re

from .knowledge import KnowledgeBase, get_knowledge_base

logger = logging.getLogger(__name__)

REASONING_SYSTEM_PROMPT = """You are Orion-Design, a senior mechanical design engineer.
You produce a structured design plan for a part BEFORE any CAD code is written.

RULES:
1. Every dimension must be justified by function or standard.
2. Bolt holes use CLEARANCE diameters (M3 -> 3.4 mm), never the nominal thread size.
3. Respect the hard facts in ENGINEERING CONSTRAINTS exactly — they come from
   part catalogs and standards tables, not from memory.
4. Plate thickness for a bracket ~= 1.5x the largest bolt diameter.
5. Hole centers stay >= 1.5x hole diameter from any edge.
6. If the user says "strong", add gussets. If "light", add lightening holes.
7. Default material: 6061-T6 aluminum unless the prompt implies 3D printing.

Respond with ONLY a JSON object (no markdown fences):
{
  "part_name": "snake_case_name",
  "material": "aluminum_6061_t6 | pla | steel_1018 | ...",
  "process": "cnc_milling | 3d_printing_fdm | sheet_metal",
  "envelope_mm": [x, y, z],
  "features": [
    {"name": "...", "type": "plate|boss|hole|pattern|slot|pocket|gusset|bore|rib",
     "dims_mm": {...}, "justification": "one sentence"}
  ],
  "joints": [
    {"name": "...", "type": "revolute|fixed|prismatic", "axis": [x,y,z],
     "limit_deg": [lo, hi]}
  ],
  "risks": ["..."]
}
"joints" is [] unless the prompt describes articulation (gimbal, hinge, arm)."""


def _extract_envelope(prompt: str) -> list[float] | None:
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm",
        prompt,
        re.I,
    )
    if m:
        return [float(m.group(i)) for i in (1, 2, 3)]
    return None


def _infer_material(prompt: str) -> str:
    p = prompt.lower()
    if any(w in p for w in ("3d print", "3d-print", "printable", "pla", "petg")):
        return "pla"
    if "steel" in p:
        return "steel_1018"
    if "delrin" in p or "acetal" in p or "pom" in p:
        return "pom_delrin"
    return "aluminum_6061_t6"


def _fallback_plan(prompt: str, sourced_parts: list[dict], kb: KnowledgeBase) -> dict:
    """Deterministic plan when no LLM is available: parts + regex extraction."""
    material = _infer_material(prompt)
    features: list[dict] = []
    for hit in sourced_parts:
        spec = hit["spec"]
        if spec.get("category") == "motor" and "mount_hole_pcd_mm" in spec:
            features.append(
                {
                    "name": f"{hit['part_id']}_mount_pattern",
                    "type": "pattern",
                    "dims_mm": {
                        "hole_dia": spec.get("mount_clearance_hole_mm"),
                        "pcd": spec["mount_hole_pcd_mm"],
                        "count": 4,
                    },
                    "justification": f"{spec['name']} bolt circle from catalog",
                }
            )
            if "pilot_boss_dia_mm" in spec:
                features.append(
                    {
                        "name": "pilot_bore",
                        "type": "bore",
                        "dims_mm": {"dia": spec["pilot_boss_dia_mm"] + 0.2},
                        "justification": "clearance for the motor pilot boss",
                    }
                )
        elif spec.get("category") == "bearing" and "od_mm" in spec:
            features.append(
                {
                    "name": f"{hit['part_id']}_seat",
                    "type": "bore",
                    "dims_mm": {
                        "dia": spec.get("seat_slip_fit_dia_mm", spec["od_mm"]),
                        "depth": spec.get("width_mm"),
                    },
                    "justification": f"{spec['name']} slip-fit seat",
                }
            )
        elif spec.get("category") == "fastener":
            features.append(
                {
                    "name": f"{spec['thread']}_clearance_holes",
                    "type": "hole",
                    "dims_mm": {"dia": spec["clearance_hole_mm"]},
                    "justification": f"{spec['thread']} clearance per ISO 273",
                }
            )
    return {
        "part_name": "generated_part",
        "material": material,
        "process": kb.material(material)["typical_processes"][0],
        "envelope_mm": _extract_envelope(prompt),
        "features": features,
        "joints": [],
        "risks": [],
        "reasoning_mode": "deterministic_fallback",
    }


def design_reasoning(
    prompt: str,
    sourced_parts: list[dict],
    kb: KnowledgeBase | None = None,
    llm=None,
) -> dict:
    """Return a structured design plan for *prompt*.

    *llm* is any object with a ``_chat(messages) -> str`` method (the existing
    OFLLLMClient qualifies). Falls back to a deterministic plan on any failure.
    """
    kb = kb or get_knowledge_base()

    if llm is None:
        return _fallback_plan(prompt, sourced_parts, kb)

    constraint_lines = kb.constraints_for_parts([h["part_id"] for h in sourced_parts])
    user = prompt
    if constraint_lines:
        user += "\n\nENGINEERING CONSTRAINTS (hard facts from catalogs):\n" + "\n".join(
            f"- {line}" for line in constraint_lines
        )

    try:
        raw = llm._chat(
            [
                {"role": "system", "content": REASONING_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
        )
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        plan = json.loads(raw)
        if not isinstance(plan, dict) or "features" not in plan:
            raise ValueError("plan missing 'features'")
        plan.setdefault("joints", [])
        plan.setdefault("risks", [])
        plan["reasoning_mode"] = "llm"
        return plan
    except Exception as e:
        logger.warning(f"design_reasoning LLM path failed ({e}); using fallback plan")
        return _fallback_plan(prompt, sourced_parts, kb)


def plan_to_brief(prompt: str, plan: dict, sourced_parts: list[dict], kb: KnowledgeBase) -> str:
    """Fold the plan + sourced-part facts into the prompt handed to the OFL
    code generator, so the code is grounded in the same numbers."""
    lines = [prompt.strip()]
    constraints = kb.constraints_for_parts([h["part_id"] for h in sourced_parts])
    if constraints:
        lines.append("\nENGINEERING CONSTRAINTS (use these EXACT numbers):")
        lines.extend(f"- {c}" for c in constraints)
    features = plan.get("features") or []
    if features:
        lines.append("\nDESIGN PLAN (follow this feature sequence):")
        for f in features:
            dims = ", ".join(f"{k}={v}" for k, v in (f.get("dims_mm") or {}).items() if v)
            lines.append(f"- {f.get('name')}: {f.get('type')} {dims}".rstrip())
    if plan.get("envelope_mm"):
        e = plan["envelope_mm"]
        lines.append(f"\nOuter envelope: {e[0]} x {e[1]} x {e[2]} mm — do not exceed it.")
    return "\n".join(lines)
