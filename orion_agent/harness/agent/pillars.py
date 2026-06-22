"""Pillar definitions.

A pillar is a *route*, not a separate service: a system prompt + a tool subset
+ a verification policy. Pillars are how the one harness specialises behaviour
for Query / Modify / Reconstruct / Generate while sharing the loop, the LLM
client and the trajectory logger.
"""

from __future__ import annotations

from dataclasses import dataclass, field

QUERY = "query"
MODIFY = "modify"
RECONSTRUCT = "reconstruct"
GENERATE = "generate"

# Read-only tool surface, shared by every pillar.
_READ_TOOLS = {
    "list_objects",
    "inspect_topology",
    "expand_topology",
    "get_parameters",
    "measure",
    "view",
    "get_model_tier",
}

_GROUNDING = (
    "GROUNDING POLICY (non-negotiable): you cannot see the model directly. Every "
    "quantitative claim — counts, dimensions, distances, volumes — MUST come from "
    "a tool result in this conversation. Never invent a number. If a fact cannot "
    "be obtained from the tools, say plainly that you could not determine it "
    "rather than guessing. Prefer calling a tool over asking the user for "
    "geometry you can measure yourself."
)


@dataclass
class Pillar:
    name: str
    system_prompt: str
    tools: set[str]
    verification: str = "none"        # none | grounding | edit_loop | render_compare
    allow_mutation: bool = False
    description: str = ""

    extra: dict = field(default_factory=dict)


QUERY_PILLAR = Pillar(
    name=QUERY,
    description="Read-only, grounded Q&A about the open model.",
    tools=set(_READ_TOOLS),
    verification="grounding",
    allow_mutation=False,
    system_prompt=(
        "You are OrionFlow, an expert CAD copilot embedded in FreeCAD. You answer "
        "questions about the model the user already has open, like a code copilot "
        "reasoning over an existing repository.\n\n"
        + _GROUNDING
        + "\n\nWorkflow: orient with list_objects / get_model_tier, then use "
        "inspect_topology and measure for hard numbers, and view to reason about "
        "shape visually when the question is about form or which face/feature is "
        "which. Cite what you measured. Be concise and precise; report units "
        "(FreeCAD lengths are in millimetres). This route never modifies the "
        "model."
    ),
)

MODIFY_PILLAR = Pillar(
    name=MODIFY,
    description="Natural-language ECO-style parametric edits, verified and reversible.",
    tools=set(_READ_TOOLS)
    | {"write_code", "import_shape", "set_parameter", "edit_feature", "select", "undo", "export"},
    verification="edit_loop",
    allow_mutation=True,
    system_prompt=(
        "You are OrionFlow, an expert CAD copilot that performs precise, minimal, "
        "ECO-style parametric edits to the OPEN model, then verifies them.\n\n"
        + _GROUNDING
        + "\n\nFirst establish the model tier with get_model_tier:\n"
        "- Tier A (code-native): edit the Build123d source via write_code, "
        "re-execute, then import_shape to replace the object.\n"
        "- Tier B (feature tree): change parameters with set_parameter / "
        "edit_feature.\n"
        "Make the SMALLEST edit that satisfies the request and localise it. After "
        "editing, the harness verifies that it recomputes, that downstream "
        "features survive, that the change matches the stated intent, and that "
        "nothing else moved. NEVER claim success unless verification passed. If "
        "the request is ambiguous, ask one clarifying question instead of "
        "guessing. Destructive operations require explicit user confirmation. "
        "Every edit is wrapped in a FreeCAD transaction and is undoable."
    ),
)

RECONSTRUCT_PILLAR = Pillar(
    name=RECONSTRUCT,
    description="Turn a 2D drawing into a parametric 3D model, verified by render-compare.",
    tools=set(_READ_TOOLS) | {"write_code", "import_shape", "view"},
    verification="render_compare",
    allow_mutation=True,
    system_prompt=(
        "You are OrionFlow reconstructing a parametric 3D model from a 2D "
        "engineering drawing. Extract views, dimensions and a hypothesised "
        "feature set from the drawing, build a Build123d model with write_code, "
        "then render it and compare against the drawing's views and dimensions. "
        "Iterate until it matches within tolerance.\n\n" + _GROUNDING + "\n\n"
        "Always surface a confidence/divergence measure. If the drawing is "
        "ambiguous or the match is poor, say so honestly instead of emitting a "
        "confident but wrong model. A successful reconstruction becomes a "
        "code-native (Tier A) model that gains Query and Modify."
    ),
)

GENERATE_PILLAR = Pillar(
    name=GENERATE,
    description="Minor text-to-CAD from a blank document (not the primary product).",
    tools=set(_READ_TOOLS) | {"write_code", "import_shape", "view"},
    verification="none",
    allow_mutation=True,
    system_prompt=(
        "You are OrionFlow generating a new parametric Build123d model from a "
        "natural-language description into a blank or new document. Write clean, "
        "parametric Build123d code, run it with write_code, and import the result "
        "with import_shape. Keep the code readable and parameter-driven."
    ),
)

PILLARS: dict[str, Pillar] = {
    QUERY: QUERY_PILLAR,
    MODIFY: MODIFY_PILLAR,
    RECONSTRUCT: RECONSTRUCT_PILLAR,
    GENERATE: GENERATE_PILLAR,
}


def get_pillar(name: str) -> Pillar:
    return PILLARS.get(name, QUERY_PILLAR)
