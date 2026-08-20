"""Tool registry — the contract between the agent loop and the world.

Each tool has an OpenAI-compatible JSON schema (what the LLM sees) and an
executor (what actually runs: a bridge capability or a sandbox run). Tools are
tagged read/write so a pillar can expose only a safe subset (Query never even
sees the mutating tools).

The registry is the single place that converts a model's ``tool_call`` into a
real effect and back into a token-bounded observation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from orion_agent.harness import featuregraph as fg
from orion_agent.harness.topology import summarize_topology, expand_shape


@dataclass
class ToolResult:
    ok: bool
    content: str                       # token-bounded text the model sees
    raw: Any = None                    # full structured result (not sent to model)
    error: str = ""
    artifacts: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]         # JSON schema
    executor: Callable[[dict], ToolResult]
    mutating: bool = False
    destructive: bool = False
    doc_mutating: bool = False         # touches the live FreeCAD document

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, allow: Optional[set[str]] = None) -> list[dict]:
        return [
            t.schema()
            for t in self._tools.values()
            if allow is None or t.name in allow
        ]

    def subset(self, names: set[str]) -> "ToolRegistry":
        r = ToolRegistry()
        for n in names:
            if n in self._tools:
                r._tools[n] = self._tools[n]
        return r

    def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"unknown tool: {name}", error="unknown_tool")
        started = time.time()
        try:
            result = tool.executor(arguments or {})
        except Exception as exc:  # noqa: BLE001 - surfaced to the model as an observation
            result = ToolResult(False, f"tool {name} raised: {exc}", error=str(exc))
        result.duration_ms = (time.time() - started) * 1000
        return result


# --------------------------------------------------------------------------- #
# Concrete tools, wired to a BridgeClient + SandboxManager
# --------------------------------------------------------------------------- #


def _ok(content: str, raw: Any = None, artifacts: Optional[list] = None) -> ToolResult:
    return ToolResult(True, content, raw=raw, artifacts=artifacts or [])


def _fail(msg: str) -> ToolResult:
    return ToolResult(False, msg, error=msg)


#: The tools that need no FreeCAD document and no sandbox: lookups over the
#: JSON knowledge assets in ``orion_agent/knowledge/**`` plus closed-form
#: engineering maths. Everything else reaches a live document.
KNOWLEDGE_TOOLS = frozenset({
    "lookup_standard",
    "lookup_mechanical_knowledge",
    "lookup_nasa_requirement",
    "resolve_design_context",
    "calculate_sheet_metal_bend",
    "check_sheet_metal_dfm",
    "lookup_robotics_knowledge",
    "get_robotics_demo",
    "validate_assembly_graph",
    "assess_robotics_assembly",
    "export_assembly_urdf",
    "validate_assembly_spec",
})

#: The tools that ask a shape questions and change nothing. They were only ever
#: coupled to a live FreeCAD document by ``build_registry``'s signature — what
#: they actually read (element topology, feature parameters, the FeatureGraph)
#: a finished build already leaves on disk. Split out so a read-only bridge over
#: an artifact can serve them without a kernel; see ``app/services/part_bridge``.
INSPECTION_TOOLS = frozenset({
    "list_objects",
    "inspect_topology",
    "expand_topology",
    "get_parameters",
    "measure",
    "get_featuregraph",
    "get_model_tier",
})


class _AbsentBridge:
    """Stands in for a BridgeClient where there is none.

    Every tool body *closes over* ``bridge`` and only touches it when called,
    so the registry can be constructed without one. The knowledge subset is
    then filtered out by name. This raises loudly if a geometry tool ever slips
    into that subset, rather than failing later somewhere subtler.
    """

    def __getattr__(self, name: str):
        def _refuse(*_args, **_kwargs):
            raise RuntimeError(
                f"tool reached FreeCAD ({name}) but no bridge is attached — "
                "this registry was built with knowledge tools only")
        return _refuse


def register_design_tool(reg: ToolRegistry) -> ToolRegistry:
    """Expose the Blueprint model as a tool: a request in, a proved part out.

    This is what binds the desktop copilot and any MCP client to the same
    engineering intelligence the studio uses. The agent loop runs on the base
    adapter because it needs tool calling; when it needs *geometry* it calls
    here, and the fine-tuned adapter answers in the only form it was trained to
    produce — a Blueprint, statically checked, built in FreeCAD, and graded
    against its own frozen assertions.

    The loop never sees a prompt template and never edits one. The request is
    passed through untouched, which is the whole reason the adapter stays on
    the distribution its accuracy was measured on.
    """
    def design_part(args):
        request = str(args.get("request", "")).strip()
        if not request:
            return _fail("'request' is required: describe the part in words")
        try:
            from app.services.studio_agent import get_studio_agent
        except Exception as exc:  # noqa: BLE001 — optional in a bare install
            return _fail(f"the design service is unavailable: {exc}")

        bundle = get_studio_agent().design(request)
        report = bundle.get("verification") or {}
        stats = bundle.get("stats") or {}
        verdict = report.get("verdict") or "not built"
        if not bundle.get("success"):
            return ToolResult(False,
                              f"the part was not built: {bundle.get('error')}",
                              raw=bundle, error=str(bundle.get("error")))

        lines = [f"verdict: {verdict}",
                 f"part class: {bundle.get('part_class')}",
                 f"volume: {stats.get('volume_mm3', 0):.3f} mm^3",
                 f"extent: {stats.get('bbox_mm')}",
                 f"watertight: {stats.get('watertight')}"]
        failed = report.get("failed") or []
        if failed:
            lines.append("FAILED CHECKS — this part did not prove itself:")
            lines += [f"  {c.get('label')}: {c.get('detail')}" for c in failed[:6]]
        else:
            lines.append(f"every check passed ({len(report.get('checks') or [])})")
        files = bundle.get("files") or {}
        if files:
            lines.append("artifacts: " + ", ".join(sorted(files)))
        return _ok("\n".join(lines), raw=bundle,
                   artifacts=[{"kind": k, "path": v} for k, v in files.items()])

    reg.register(Tool(
        "design_part",
        "Generate a NEW parametric part from a description, using OrionFlow's "
        "own fine-tuned CAD model. Returns a part that has been built in "
        "FreeCAD and graded against the closed-form volume the model predicted "
        "for it, so the verdict says whether it proved itself. Use this to "
        "create geometry; use the editing tools to change geometry that "
        "already exists.",
        {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The part, in plain words, with any "
                                   "dimensions the user gave. Pass their "
                                   "wording through — do not reformat it.",
                },
            },
            "required": ["request"],
        },
        design_part,
        mutating=True,
    ))
    return reg


def register_skills(reg: ToolRegistry) -> ToolRegistry:
    """Engineering skills, as tools.

    A skill answers in engineering terms — "a housing for a 6205" — and resolves
    the CAD vocabulary itself. That is what removes the invented-builder class of
    failure: the model cannot misname a profile builder it is never shown.

    Each returns the variables of a real part family, already checked against
    that family's guards, so nothing here can smuggle geometry past the verifier.
    """
    from orion.skills import registry as skills
    from orion.skills.base import SkillError

    def make(skill_name: str):
        def call(args):
            try:
                result = skills.execute(skill_name, args or {})
            except SkillError as exc:
                # A refusal is the useful answer. It names what is missing and
                # what is known, which is what lets the next turn fix it.
                return _fail(str(exc))
            except TypeError as exc:
                return _fail(f"wrong arguments for {skill_name}: {exc}")
            return _ok(result.summary(), raw=result.to_dict())
        return call

    for skill in (skills.get(n) for n in skills.names()):
        reg.register(Tool(skill.name, skill.description, skill.parameters,
                          make(skill.name)))
    return reg


def build_knowledge_registry() -> ToolRegistry:
    """The FreeCAD-free half of the tool surface.

    The knowledge was never FreeCAD-dependent — it is JSON on disk plus
    closed-form maths. Only ``build_registry``'s signature coupled it to a live
    document, which put ISO/DIN/NASA/materials lookup out of reach of the cloud
    Studio for no reason at all. Same tools, same schemas, same executors; just
    the ones that never touch geometry.
    """
    reg = build_registry(_AbsentBridge(), None).subset(KNOWLEDGE_TOOLS)
    return register_skills(register_design_tool(reg))


def build_part_registry(bridge) -> ToolRegistry:
    """Knowledge plus inspection, bound to a read-only bridge over one build.

    The half of the tool surface that a cloud session can honestly offer: the
    model can look a standard up *and* go and check what was actually built,
    but it cannot edit — a change to a graded part has to go back through
    freeze, build and verify, and a tool call would bypass all three.

    ``bridge`` only has to answer the inspection calls (``list_objects``,
    ``inspect_topology``, ``get_object_parameters``, ``measure``,
    ``extract_featuregraph``, ``get_model_tier``). Anything else it is asked for
    should raise; the registry turns that into an observation the model can read.
    """
    reg = build_registry(bridge, None).subset(KNOWLEDGE_TOOLS | INSPECTION_TOOLS)
    return register_skills(register_design_tool(reg))


def build_registry(bridge, sandbox) -> ToolRegistry:
    """Construct the full tool surface bound to a bridge client and sandbox.

    ``bridge`` is a :class:`~orion_agent.harness.bridge_client.BridgeClient`;
    ``sandbox`` is a :class:`~orion_agent.harness.sandbox.SandboxManager`.
    """
    reg = ToolRegistry()

    # Remember the most recent sandbox STEP artifact so import_shape can fall
    # back to it when the model echoes back a wrong/relative path (it routinely
    # guesses "result.step" instead of the absolute path we hand it), and the
    # code that produced it so the import stays Tier A (source travels with the
    # shape instead of degrading to a dumb B-rep).
    _state: dict[str, Optional[str]] = {"last_step": None, "last_code": None}

    # ---- read ----------------------------------------------------------- #
    def list_objects(_args):
        raw = bridge.list_objects()
        objs = raw.get("objects", [])
        lines = [
            f"- {o['name']} ({o['type_id']}) "
            f"{'parametric' if o.get('parametric') else 'imported'}"
            + (f", {o['faces']} faces" if "faces" in o else "")
            for o in objs
        ]
        return _ok("\n".join(lines) or "no objects", raw=raw)

    reg.register(Tool(
        "list_objects",
        "List every object in the open document with its type and whether it is "
        "parametric or an imported B-rep. Use first to orient yourself.",
        {"type": "object", "properties": {}},
        list_objects,
    ))

    def inspect_topology(args):
        raw = bridge.inspect_topology(args.get("name"))
        return _ok(summarize_topology(raw), raw=raw)

    reg.register(Tool(
        "inspect_topology",
        "Get real topology of the model (or one named object): solid/face/edge/"
        "vertex counts, surface & curve types, cylindrical-face count, bounding "
        "box, volume, centre of mass. This is ground truth — use it for any "
        "quantitative claim instead of guessing.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name; omit for whole model"}
            },
        },
        inspect_topology,
    ))

    def expand_topology(args):
        raw = bridge.inspect_topology(None)
        return _ok(expand_shape(raw, args.get("name", "")), raw=raw)

    reg.register(Tool(
        "expand_topology",
        "Drill into one named shape for full detail (curve types, exact bbox).",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        expand_topology,
    ))

    def lookup_standard(args):
        from orion_agent.harness import standards
        hits = standards.search(args.get("query", ""))
        if not hits:
            return _fail(
                "no standard matched; try a bearing designation (6204, 32005), "
                "'tapered roller bore 20', 'NEMA 17', or a thread size 'M5'"
            )
        return _ok(standards.render(hits), raw={"results": hits})

    reg.register(Tool(
        "lookup_standard",
        "Look up engineering-standard dimensions: bearings (by designation "
        "like 6204/32005, or 'tapered roller bore 20'), ISO metric fasteners "
        "(M2..M20 — clearance/tap/counterbore/head/nut), NEMA stepper mounts "
        "(bolt pattern, pilot, shaft). These numbers are authoritative — use "
        "them instead of recalling values from memory.",
        {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "e.g. '6204', 'NEMA 23', "
                                                    "'M5', 'ball bearing bore 25'"}},
            "required": ["query"],
        },
        lookup_standard,
    ))

    def lookup_mechanical_knowledge(args):
        from orion_agent.harness import mechanical_knowledge as mk
        hits = mk.search(args.get("query", ""), domain=args.get("domain", ""))
        if not hits:
            return _fail(
                "no mechanical knowledge item matched; try a domain or terms such as "
                "'datum', 'feature control frame', 'bend allowance', 'bend relief', "
                "'holes', 'grain direction', or 'threads'"
            )
        return _ok(mk.render(hits), raw={"results": hits})

    reg.register(Tool(
        "lookup_mechanical_knowledge",
        "Retrieve traceable mechanical-engineering knowledge for GD&T, sheet-metal "
        "DFM, fastener governance, and knowledge provenance. Every result names its "
        "source authority and maturity. A secondary reference or screening guideline "
        "is NOT standards-compliance evidence; state that limitation in your answer.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Engineering question or topic"},
                "domain": {"type": "string", "description": "Optional: gdt, sheet_metal, fasteners, governance"},
            },
            "required": ["query"],
        },
        lookup_mechanical_knowledge,
    ))

    def lookup_nasa_requirement(args):
        from orion_agent.harness import nasa_rules
        hits = nasa_rules.search(
            args.get("query", ""),
            domain=args.get("domain", ""),
            standard=args.get("standard", ""),
            numeric_only=bool(args.get("numeric_only")),
        )
        if not hits:
            return _fail(
                "no NASA requirement matched; try terms such as 'preload', "
                "'factor of safety', 'fitting factor', 'weld inspection', "
                "'mechanism clearance', 'fracture control', 'material "
                "selection', or an exact tag like 'TFSR 3'"
            )
        return _ok(nasa_rules.render(hits), raw={"results": hits})

    reg.register(Tool(
        "lookup_nasa_requirement",
        "Retrieve verbatim normative requirements from public NASA Technical "
        "Standards (factors of safety 5001, loads 5002, welding 5006, NDE 5009, "
        "mechanisms 5017, fracture control 5019, threaded fasteners 5020, "
        "materials 6016). Every result is quoted with its requirement tag, "
        "section, and page, so cite the tag rather than paraphrasing. These bind "
        "NASA spaceflight hardware: use them as engineering defaults, and never "
        "tell the user their part is compliant.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Topic or exact tag, e.g. 'bolt preload', "
                                         "'minimum factor of safety', 'TFSR 3'"},
                "domain": {"type": "string",
                           "description": "Optional: fasteners, structural_margins, "
                                          "loads, joining, inspection, mechanisms, "
                                          "fracture_control, materials"},
                "standard": {"type": "string",
                             "description": "Optional, e.g. 'NASA-STD-5020'"},
                "numeric_only": {"type": "boolean",
                                 "description": "Only requirements carrying numbers"},
            },
            "required": ["query"],
        },
        lookup_nasa_requirement,
    ))

    def resolve_design_context(args):
        """Datum, material and process facts for a request — looked up, not recalled."""
        from orion_agent.harness import design_rules
        ctx = design_rules.resolve(
            args.get("request", ""),
            part=args.get("part", ""),
            material=args.get("material", ""),
            manufacturing=args.get("manufacturing", ""),
            dimensions=args.get("dimensions") or {},
            counts=args.get("counts") or {},
        )
        text = ctx.render()
        if not text:
            return _fail("could not classify the request into a part class")
        return _ok(text, raw=ctx.to_dict())

    reg.register(Tool(
        "resolve_design_context",
        "Resolve the modelling convention and engineering facts for a part BEFORE "
        "writing a FeatureGraph: part class, sketch plane / axis / symmetry datum, "
        "feature order, material properties (density, yield, modulus), "
        "manufacturing constraints (min wall, draft, corner radius, tolerance), and "
        "derived values computed from stated dimensions. Every number here is "
        "looked up or computed - prefer it over your own recollection, and use the "
        "given datum rather than choosing a plane yourself.",
        {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The user's request, verbatim"},
                "part": {"type": "string", "description": "Optional part name"},
                "material": {"type": "string", "description": "Optional stated material"},
                "manufacturing": {"type": "string", "description": "Optional stated process"},
                "dimensions": {"type": "object", "description": "Optional {name: mm} already extracted"},
                "counts": {"type": "object", "description": "Optional {noun: n} already extracted"},
            },
            "required": ["request"],
        },
        resolve_design_context,
    ))

    def calculate_sheet_metal_bend(args):
        from orion_agent.harness import mechanical_knowledge as mk
        try:
            raw = mk.calculate_bend(
                thickness_mm=args.get("thickness_mm"),
                inside_radius_mm=args.get("inside_radius_mm"),
                bend_angle_deg=args.get("bend_angle_deg"),
                k_factor=args.get("k_factor"),
                flange_a_mm=args.get("flange_a_mm"),
                flange_b_mm=args.get("flange_b_mm"),
            )
        except mk.KnowledgeInputError as exc:
            return _fail(str(exc))
        return _ok(mk.render_bend_calculation(raw), raw=raw)

    reg.register(Tool(
        "calculate_sheet_metal_bend",
        "Calculate one sheet-metal bend's allowance and deduction using the supplied "
        "thickness, inside radius, bend angle, and K-factor. Use only a K-factor "
        "provided by the user or a validated process source. This is a preliminary "
        "flat-pattern estimate and requires fabricator confirmation before release.",
        {
            "type": "object",
            "properties": {
                "thickness_mm": {"type": "number"},
                "inside_radius_mm": {"type": "number"},
                "bend_angle_deg": {"type": "number"},
                "k_factor": {"type": "number"},
                "flange_a_mm": {"type": "number", "description": "Optional outside flange length"},
                "flange_b_mm": {"type": "number", "description": "Optional outside flange length"},
            },
            "required": ["thickness_mm", "inside_radius_mm", "bend_angle_deg", "k_factor"],
        },
        calculate_sheet_metal_bend,
    ))

    def check_sheet_metal_dfm(args):
        from orion_agent.harness import mechanical_knowledge as mk
        try:
            raw = mk.check_sheet_metal_dfm(
                thickness_mm=args.get("thickness_mm"),
                inside_radius_mm=args.get("inside_radius_mm"),
                hole_diameter_mm=args.get("hole_diameter_mm"),
                hole_spacing_mm=args.get("hole_spacing_mm"),
                hole_edge_distance_mm=args.get("hole_edge_distance_mm"),
                bend_relief_width_mm=args.get("bend_relief_width_mm"),
                bend_relief_depth_mm=args.get("bend_relief_depth_mm"),
            )
        except mk.KnowledgeInputError as exc:
            return _fail(str(exc))
        return _ok(mk.render_dfm_check(raw), raw=raw)

    reg.register(Tool(
        "check_sheet_metal_dfm",
        "Run source-aware, preliminary sheet-metal checks for hole diameter/spacing "
        "and bend-relief dimensions. Results are warnings only, never supplier approval. "
        "Hole-to-edge distance is intentionally review-only until its source conflict is "
        "resolved by an engineer.",
        {
            "type": "object",
            "properties": {
                "thickness_mm": {"type": "number"},
                "inside_radius_mm": {"type": "number"},
                "hole_diameter_mm": {"type": "number"},
                "hole_spacing_mm": {"type": "number"},
                "hole_edge_distance_mm": {"type": "number"},
                "bend_relief_width_mm": {"type": "number"},
                "bend_relief_depth_mm": {"type": "number"},
            },
            "required": ["thickness_mm"],
        },
        check_sheet_metal_dfm,
    ))

    def lookup_robotics_knowledge(args):
        from orion_agent.harness import robotics_knowledge as rk
        try:
            hits = rk.search(args.get("query", ""), kind=args.get("kind", ""))
        except rk.RoboticsKnowledgeError as exc:
            return _fail(str(exc))
        if not hits:
            return _fail(
                "no robotics knowledge matched; try 'linear axis', 'parallel jaw "
                "gripper', 'pan tilt', 'harmonic drive', 'motor mount', 'belt', or "
                "'assembly demo'"
            )
        return _ok(rk.render(hits), raw={"results": hits})

    reg.register(Tool(
        "lookup_robotics_knowledge",
        "Retrieve source-aware robotics components, interface contracts, and demo "
        "assemblies. Each result exposes its data status: source_specific facts still "
        "need current drawing/revision review; candidate and illustrative records must "
        "never be presented as selected, safe, or production-ready hardware.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Robotics component, interface, or demo topic"},
                "kind": {"type": "string", "description": "Optional: component, interface, or demo"},
            },
            "required": ["query"],
        },
        lookup_robotics_knowledge,
    ))

    def get_robotics_demo(args):
        from orion_agent.harness import robotics_knowledge as rk
        demo_id = args.get("demo_id", "")
        try:
            demo = rk.get("demo", demo_id)
            if demo is None:
                return _fail(f"unknown robotics demo: {demo_id}")
            composition_graph = rk.demo_composition_graph(demo_id)
            errors = rk.validate_demo_graph(demo)
        except rk.RoboticsKnowledgeError as exc:
            return _fail(str(exc))
        if errors:
            return _fail(
                "packaged demo composition graph is invalid; do not use it until fixed:\n- "
                + "\n- ".join(errors[:12])
            )
        content = rk.render_demo_manifest(demo, rk.summarize_demo_topology(demo))
        return _ok(content, raw={
            "demo": demo,
            "composition_graph": composition_graph,
        })

    reg.register(Tool(
        "get_robotics_demo",
        "Load a validated robotics demonstration manifest and its high-level component "
        "composition graph. "
        "Use this before creating the custom parts for a supported demo. It returns "
        "a component/interface plan, not a mate-solved AssemblyGraph or finished FreeCAD "
        "assembly; resolve all candidate hardware, frames, mates and limits against exact "
        "supplier drawings first.",
        {
            "type": "object",
            "properties": {
                "demo_id": {"type": "string", "description": "Stable demo ID from lookup_robotics_knowledge"},
            },
            "required": ["demo_id"],
        },
        get_robotics_demo,
    ))

    def validate_assembly_graph(args):
        from orion_agent.harness import assembly_graph as ag
        try:
            canonical = ag.normalize(args.get("graph"))
            errors = ag.validate(canonical)
        except ag.AssemblyGraphError as exc:
            return _fail(str(exc))
        if errors:
            return _fail(
                "AssemblyGraph invalid - fix and retry:\n- " + "\n- ".join(errors[:12])
            )
        graph = ag.parse_assembly_graph(canonical)
        bom = ag.aggregate_bom(graph)
        bom_text = "\n".join(
            f"- {line['quantity']} x {line['part_number']}"
            + (f" ({line['name']})" if line.get("name") else "")
            for line in bom
        )
        content = ag.summarize(graph) + "\nBOM:\n" + (bom_text or "- no parts")
        return _ok(content, raw={"assembly_graph": canonical, "bom": bom})

    reg.register(Tool(
        "validate_assembly_graph",
        "Validate a multi-part AssemblyGraph before CAD generation. The graph contains "
        "part instances, interface frames, fixed/revolute/prismatic joints, and optional "
        "limits. The tool checks references, axes, limits, connectivity, topology and BOM. "
        "It is a planning validator only: it does not solve mates, create CAD, or approve "
        "a physical robot.",
        {
            "type": "object",
            "properties": {
                "graph": {
                    "type": "object",
                    "description": "AssemblyGraph: {id, parts, interfaces, joints}; use exact declared interface IDs",
                },
            },
            "required": ["graph"],
        },
        validate_assembly_graph,
    ))

    def compile_assembly_graph(args):
        """Place explicitly bound source parts as a native linked assembly.

        AssemblyGraph deliberately does not name FreeCAD objects.  Keeping the
        binding map at this tool boundary prevents a model from treating a
        component catalogue entry or part number as permission to select an
        arbitrary object in the user's document.
        """
        from orion_agent.harness import assembly_graph as ag

        bindings = args.get("bindings")
        if not isinstance(bindings, dict) or not bindings:
            return _fail(
                "'bindings' must explicitly map every AssemblyGraph part id to an "
                "existing FreeCAD source-object name"
            )
        if not all(isinstance(part_id, str) and isinstance(name, str)
                   and part_id and name for part_id, name in bindings.items()):
            return _fail("every binding must be a non-empty {part_id: source_object_name} string pair")
        root_part_id = args.get("root_part_id")
        if not isinstance(root_part_id, str) or not root_part_id:
            return _fail("'root_part_id' must name the grounded AssemblyGraph part instance")
        joint_values = args.get("joint_values")
        if joint_values is not None and not isinstance(joint_values, dict):
            return _fail("'joint_values' must be an object mapping joint ids to numeric positions")

        try:
            canonical = ag.normalize(args.get("graph"))
            errors = ag.validate(canonical)
        except ag.AssemblyGraphError as exc:
            return _fail(str(exc))
        if errors:
            return _fail(
                "AssemblyGraph invalid - fix and retry before compiling:\n- "
                + "\n- ".join(errors[:12])
            )

        graph = ag.parse_assembly_graph(canonical)
        raw = bridge.compile_assembly_graph(
            canonical,
            bindings=bindings,
            root_part_id=root_part_id,
            joint_values=joint_values,
            label=args.get("label"),
        )
        warnings = raw.get("warnings", []) if isinstance(raw, dict) else []
        if not isinstance(raw, dict) or not raw.get("recompute_ok", False):
            return ToolResult(
                False,
                "assembly compile FAILED - FreeCAD did not recompute the linked assembly cleanly",
                raw=raw,
                error="recompute_failed",
            )

        assembly = raw.get("assembly", {}) or {}
        instances = raw.get("instances", []) or []
        lines = [
            f"compiled native linked assembly '{assembly.get('name', 'assembly')}' "
            f"with {len(instances)} placed occurrence(s) (backend: "
            f"{assembly.get('backend', 'core_links')})",
            "Source parts remain separate; this is deterministic placement from explicit "
            "frames/joint values, not collision, load, safety, or release approval.",
            ag.summarize(graph),
        ]
        if warnings:
            lines.append("warnings: " + "; ".join(str(item) for item in warnings[:6]))
        return _ok("\n".join(lines), raw=raw)

    reg.register(Tool(
        "compile_assembly_graph",
        "Compile a validated, explicitly grounded AssemblyGraph into a native FreeCAD "
        "linked assembly. Provide a binding for every part instance to an existing source "
        "object in the active document, a root part id, and optional numeric joint values. "
        "The v0 backend places a rooted tree of App::Link occurrences; it refuses missing "
        "frames, loops, duplicate parents, undefined source objects, and out-of-limit "
        "positions. It does not infer mates, select hardware, solve collisions, or certify "
        "the mechanical design.",
        {
            "type": "object",
            "properties": {
                "graph": {
                    "type": "object",
                    "description": "Strict AssemblyGraph with explicit interface frames and joints",
                },
                "bindings": {
                    "type": "object",
                    "description": "Exact {part_instance_id: existing_FreeCAD_object_name} map",
                },
                "root_part_id": {
                    "type": "string",
                    "description": "Grounded AssemblyGraph part instance id",
                },
                "joint_values": {
                    "type": "object",
                    "description": "Optional {joint_id: position}; revolute in radians, prismatic in mm",
                },
                "label": {"type": "string", "description": "Optional label for the assembly container"},
            },
            "required": ["graph", "bindings", "root_part_id"],
        },
        compile_assembly_graph,
        mutating=True,
        doc_mutating=True,
    ))

    def assess_robotics_assembly(args):
        from orion_agent.harness import assembly_graph as ag
        from orion_agent.harness import robotics_assembly as ra
        try:
            raw = ra.assess_readiness(args.get("graph"))
        except ag.AssemblyGraphError as exc:
            return _fail(str(exc))
        return _ok(ra.render_readiness(raw), raw=raw)

    reg.register(Tool(
        "assess_robotics_assembly",
        "Assess an explicit AssemblyGraph against the controlled robotics component "
        "catalogue. It reports whether every referenced part is source-specific and "
        "engineering-reviewed, while keeping candidates/illustrative records in planning "
        "status. This is a provenance gate only; it does not approve mechanics, safety, "
        "mates, loads, collision, or manufacturing.",
        {
            "type": "object",
            "properties": {
                "graph": {"type": "object", "description": "Structurally valid AssemblyGraph"},
            },
            "required": ["graph"],
        },
        assess_robotics_assembly,
    ))

    def export_assembly_urdf(args):
        from orion_agent.harness import assembly_graph as ag
        from orion_agent.harness import urdf_export as ue
        try:
            graph = ag.parse_assembly_graph(args.get("graph"))
            xml = ue.export_urdf(graph, robot_name=args.get("robot_name"))
        except (ag.AssemblyGraphError, ue.URDFExportError) as exc:
            return _fail(str(exc))
        warning = (
            "URDF kinematic skeleton generated. It intentionally omits visual meshes, "
            "collision meshes, inertias, transmissions, and physical safety claims. "
            "Validate it with the target ROS/simulation workflow after source and frame review."
        )
        # Tool observations are token-bounded. The full XML remains in raw for
        # API consumers; a small graph is also visible to the model for review.
        preview = xml if len(xml) <= 6000 else xml[:5800] + "\n<!-- truncated in agent observation -->\n"
        return _ok(warning + "\n\n```xml\n" + preview + "```", raw={
            "urdf": xml,
            "robot_name": args.get("robot_name") or graph.id,
            "kinematic_only": True,
        })

    reg.register(Tool(
        "export_assembly_urdf",
        "Export a validated AssemblyGraph as a conservative kinematic-only URDF. "
        "Every joint must explicitly provide metadata.urdf_origin {xyz, rpy}; movable "
        "joints also require an axis and lower/upper/velocity/effort limits. The graph "
        "must be one rooted tree. This tool refuses to invent visual, collision, inertial, "
        "or transmission data and does not certify the physical robot.",
        {
            "type": "object",
            "properties": {
                "graph": {"type": "object", "description": "Explicit, mate-reviewed AssemblyGraph"},
                "robot_name": {"type": "string", "description": "Optional URDF robot name"},
            },
            "required": ["graph"],
        },
        export_assembly_urdf,
    ))

    def validate_assembly_spec(args):
        from orion_agent.harness import assembly_spec as asp
        from orion_agent.harness import assembly_validation as av
        try:
            spec = asp.parse_assembly_spec(args.get("spec"), strict=False)
        except asp.AssemblySpecError as exc:
            return _fail(str(exc))
        result = av.run_validation(spec)
        return _ok(av.render_validation(result), raw=result)

    reg.register(Tool(
        "validate_assembly_spec",
        "Run the ordered assembly validation pipeline (geometry -> interfaces/mates "
        "-> DFM -> closed-form calculations -> collision/kinematics -> mass/CoG -> "
        "FEA evidence) over an AssemblySpec {id, requirements, variants, contracts, "
        "graph, links, evidence}. Deterministic screening only: missing data becomes "
        "an evidence_required finding, never a silent pass, and no stage result is a "
        "release, safety, or supplier approval.",
        {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "AssemblySpec with graph, component variants, links, and declared calculations",
                },
            },
            "required": ["spec"],
        },
        validate_assembly_spec,
    ))

    def get_parameters(args):
        raw = bridge.get_object_parameters(args["name"])
        params = raw.get("parameters", {})
        keep = {k: v for k, v in params.items() if not k.startswith(("Visibility", "Shape"))}
        text = json.dumps(keep, default=str)
        if len(text) > 1500:
            # Trim whole entries, never mid-string: the model must always see
            # valid JSON, plus a count of what was left out.
            slim: dict = {}
            for k, v in keep.items():
                slim[k] = v
                if len(json.dumps(slim, default=str)) > 1400:
                    slim.pop(k)
            slim["_omitted_properties"] = len(keep) - len(slim)
            text = json.dumps(slim, default=str)
        return _ok(text, raw=raw)

    reg.register(Tool(
        "get_parameters",
        "Read the editable parameters of a parametric feature (e.g. a Pad's "
        "Length, a sketch constraint). Returns the property dictionary.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        get_parameters,
    ))

    def measure(args):
        raw = bridge.measure(args.get("a", {}), args.get("b", {}))
        distance = raw.get("distance")
        # A bridge that knows how it reached the number says so, and the model
        # is told in the observation rather than in the raw dict it never sees.
        # An estimate reported as a measurement is worse than no measurement:
        # it is a number nobody thinks to question. The live-document bridge
        # returns a true minimum and no method, and reads exactly as before.
        method = raw.get("method")
        if method and raw.get("exact") is False:
            text = (f"distance ~= {distance} mm — this is NOT an exact minimum "
                    f"distance. Method: {method}.")
            if raw.get("lower_bound") is not None:
                text += f" Proved lower bound {raw['lower_bound']} mm."
            if raw.get("centroid_distance") is not None:
                text += f" Centroid separation {raw['centroid_distance']} mm."
            text += " Report it as a bound, not as the distance."
        elif method:
            text = f"distance = {distance} mm (exact — {method})"
        else:
            text = f"distance = {distance} mm"
        return _ok(text, raw=raw)

    reg.register(Tool(
        "measure",
        "Measure the minimum distance between two sub-elements. Each ref is "
        "{name, sub} where sub is e.g. 'Face3', 'Edge5', 'Vertex2'. The answer "
        "says whether it is exact or an estimate — quote it the way it comes back.",
        {
            "type": "object",
            "properties": {
                "a": {"type": "object", "description": "{name, sub}"},
                "b": {"type": "object", "description": "{name, sub}"},
            },
            "required": ["a", "b"],
        },
        measure,
    ))

    def view(args):
        raw = bridge.render_views(args.get("views"))
        renders = raw.get("renders", [])
        if raw.get("headless"):
            return _ok("(render unavailable in headless mode)", raw=raw)
        arts = [{"kind": "render", "path": r["path"], "label": r["view"]} for r in renders]
        return _ok(
            f"rendered {len(renders)} view(s): {', '.join(r['view'] for r in renders)}",
            raw=raw, artifacts=arts,
        )

    reg.register(Tool(
        "view",
        "Render named viewpoints of the model to images so you can reason about "
        "shape visually. Views: isometric, front, rear, top, bottom, left, right.",
        {
            "type": "object",
            "properties": {
                "views": {"type": "array", "items": {"type": "string"}},
            },
        },
        view,
    ))

    def get_model_tier(_args):
        raw = bridge.get_model_tier()
        return _ok(f"tier {raw.get('tier')} — {raw.get('rationale')}", raw=raw)

    reg.register(Tool(
        "get_model_tier",
        "Classify how editable the open model is: A=code-native, B=feature-tree, "
        "C=imported B-rep with no history. Determines which edit path is valid.",
        {"type": "object", "properties": {}},
        get_model_tier,
    ))

    def get_featuregraph(_args):
        raw = bridge.extract_featuregraph()
        graph = raw.get("graph", {}) or {}
        return _ok(fg.summarize_graph(graph), raw=raw)

    reg.register(Tool(
        "get_featuregraph",
        "Extract the open document's parametric FeatureGraph: the feature tree "
        "as structured IR (sketches, solid features, profile dependencies, key "
        "parameters). Use it to understand how the model was built before "
        "editing or answering structural questions.",
        {"type": "object", "properties": {}},
        get_featuregraph,
    ))

    # ---- write ---------------------------------------------------------- #
    def create_featuregraph(args):
        graph = fg.parse_graph_arg(args.get("graph"))
        if graph is None:
            return _fail("'graph' must be a JSON object with features/sketches/dependencies")
        canonical, notes = fg.normalize(graph)
        errors = fg.validate(canonical)
        if errors:
            return _fail("FeatureGraph invalid — fix and retry:\n- "
                         + "\n- ".join(errors[:12]))
        raw = bridge.compile_featuregraph(canonical)
        report = raw.get("report", {}) or {}
        problems = report.get("recompute_errors", []) or []
        lines = []
        if notes:
            lines.append("normalizer: " + "; ".join(notes[:6]))
        if report.get("unsupported"):
            lines.append(f"skipped unsupported: {report['unsupported']}")
        if problems or not raw.get("recompute_ok", False):
            detail = "; ".join(f"{p.get('id')}: {p.get('error')}" for p in problems[:6])
            return ToolResult(
                False,
                "compile FAILED — the graph did not rebuild cleanly: "
                + (detail or "document recompute error") + "\n"
                + "\n".join(lines),
                raw=raw, error="recompute_failed",
            )
        volume = report.get("volume")
        if volume is not None and float(volume) <= 1e-6:
            return ToolResult(
                False,
                "compile FAILED — the graph rebuilt but produced zero volume "
                "(an empty solid is never the requested part)\n" + "\n".join(lines),
                raw=raw, error="zero_volume",
            )
        built = report.get("built", [])
        lines.insert(0, (
            f"compiled {len(built)} feature(s) into the document as a native "
            f"parametric feature tree (body: {raw.get('body')}, "
            f"volume: {report.get('volume')} mm^3)"
        ))
        return _ok("\n".join(lines), raw=raw)

    reg.register(Tool(
        "create_featuregraph",
        "Build a new parametric model by describing it as a FeatureGraph — the "
        "preferred way to create geometry. The graph compiles deterministically "
        "into native, editable FreeCAD PartDesign features (real sketches, "
        "pads, pockets), so the user can edit every dimension afterwards. "
        + fg.AUTHORING_GUIDE,
        {
            "type": "object",
            "properties": {
                "graph": {
                    "type": "object",
                    "description": "FeatureGraph: {features:[...], sketches:[...],"
                                   " dependencies:[...]} per the authoring guide",
                },
            },
            "required": ["graph"],
        },
        create_featuregraph,
        mutating=True,
        doc_mutating=True,
    ))

    def write_code(args):
        result = sandbox.run_code(
            args["code"], result_var=args.get("result_var", "result"),
            exports=args.get("exports", ["step", "stl"]),
        )
        if not result.ok:
            return ToolResult(
                False,
                f"sandbox failed: {result.error[:600]}",
                raw=result.to_dict(), error=result.error,
            )
        from orion_agent.harness.topology import summarize_topology as _st
        content = "sandbox OK\n" + _st(result.topology)
        arts = [{"kind": a["kind"], "path": a["path"]} for a in result.artifacts if a.get("path")]
        step_path = result.artifact_path("step")
        if step_path:
            _state["last_step"] = step_path
            _state["last_code"] = args["code"]
            content += (
                f"\nSTEP artifact: {step_path}\n"
                "To place this in the document, call import_shape with this exact "
                "path (or with no path to use this latest artifact)."
            )
        return _ok(content, raw=result.to_dict(), artifacts=arts)

    reg.register(Tool(
        "write_code",
        "Execute Build123d Python in the sandbox and assign the final solid to a "
        "variable named 'result'. The sandbox exports 'result' automatically and "
        "returns topology + STEP/STL — do NOT call export_step/export_stl and do "
        "NOT import any build123d submodule (no `import build123d.opengl`); "
        "`from build123d import *` is all you need. Runs isolated — never in "
        "FreeCAD.\n"
        "Build123d is NOT CadQuery: there is no make_cylinder()/make_box() free "
        "function. Use the algebra/primitive API. Canonical examples:\n"
        "  from build123d import *\n"
        "  result = Cylinder(radius=5, height=40)          # 10mm dia x 40mm tall\n"
        "  result = Box(10, 20, 5)\n"
        "  result = Sphere(8)\n"
        "  result = Box(20, 20, 10) - Cylinder(radius=3, height=10)  # boolean cut\n"
        "Builder form also works:\n"
        "  with BuildPart() as p:\n"
        "      Cylinder(radius=5, height=40)\n"
        "  result = p.part\n"
        "Primitives: Box, Cylinder, Cone, Sphere, Torus, Wedge. Use real "
        "newlines in the code string.",
        {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Build123d python; assign the final solid to 'result'. "
                    "Use Cylinder(radius=, height=)/Box(l,w,h)/Sphere(r) — NOT "
                    "make_cylinder. No export calls and no submodule imports. Real newlines.",
                },
                "exports": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["code"],
        },
        write_code,
        mutating=True,
    ))

    def import_shape(args):
        import os as _os
        path = args.get("path") or ""
        # The model frequently passes a guessed/relative path or none at all;
        # fall back to the last sandbox STEP artifact, which is the thing it just
        # built. Only override when the given path does not actually resolve.
        source = None
        if (not path or not _os.path.isabs(path) or not _os.path.exists(path)) and _state.get("last_step"):
            path = _state["last_step"]
        # Attach the generating code when the imported STEP is the sandbox one.
        if path == _state.get("last_step"):
            source = _state.get("last_code")
        raw = bridge.import_shape(path, args.get("label", "OrionResult"),
                                  args.get("replace"), source_code=source)
        return _ok(json.dumps(raw), raw=raw)

    reg.register(Tool(
        "import_shape",
        "Import the sandbox-produced STEP artifact into the live document, "
        "optionally replacing an existing object by name. Omit 'path' (or pass "
        "the STEP path from the latest write_code result) to import the model you "
        "just built.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "label": {"type": "string"},
                "replace": {"type": "string"},
            },
        },
        import_shape,
        mutating=True,
        doc_mutating=True,
    ))

    def set_parameter(args):
        raw = bridge.set_parameter(args["name"], args["property"], args["value"])
        return _ok(
            f"{raw['name']}.{raw['property']}: {raw['before']} → {raw['after']}", raw=raw
        )

    reg.register(Tool(
        "set_parameter",
        "Change one parameter of a parametric feature (Tier B edit) and "
        "recompute. Fails (and reports) if the recompute breaks.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "property": {"type": "string"},
                "value": {},
            },
            "required": ["name", "property", "value"],
        },
        set_parameter,
        mutating=True,
        doc_mutating=True,
    ))

    def edit_feature(args):
        raw = bridge.edit_feature(args["name"], args.get("properties", {}))
        return _ok(json.dumps(raw["applied"], default=str)[:800], raw=raw)

    reg.register(Tool(
        "edit_feature",
        "Apply several parameter changes to one feature at once, then recompute.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "properties": {"type": "object"},
            },
            "required": ["name", "properties"],
        },
        edit_feature,
        mutating=True,
        doc_mutating=True,
    ))

    def select(args):
        raw = bridge.select(args.get("refs", []))
        return _ok(json.dumps(raw), raw=raw)

    reg.register(Tool(
        "select",
        "Highlight/select objects or sub-elements in the FreeCAD GUI so the user "
        "sees what you are referring to. refs: [{name, sub}].",
        {
            "type": "object",
            "properties": {"refs": {"type": "array", "items": {"type": "object"}}},
            "required": ["refs"],
        },
        select,
        mutating=False,
    ))

    def export(args):
        raw = bridge.export(args["path"], args.get("names"))
        return _ok(f"exported to {raw['path']}", raw=raw)

    reg.register(Tool(
        "export",
        "Export the model (or named objects) to a STEP/STL file path.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "names": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["path"],
        },
        export,
        mutating=False,
    ))

    def undo(_args):
        return _ok(json.dumps(bridge.undo()))

    reg.register(Tool(
        "undo", "Undo the last change (revert one FreeCAD transaction).",
        {"type": "object", "properties": {}}, undo, mutating=True,
    ))

    # ---- documents ------------------------------------------------------- #
    def list_documents(_args):
        raw = bridge.list_documents()
        docs = raw.get("documents", [])
        if not docs:
            return _ok("no documents open", raw=raw)
        lines = ["%s%s  (%s, %d objects)%s"
                 % ("* " if d["active"] else "  ", d["label"], d["name"],
                    d["object_count"], "  [modified]" if d["modified"] else "")
                 for d in docs]
        return _ok("\n".join(lines), raw=raw)

    reg.register(Tool(
        "list_documents",
        "List every open FreeCAD document and which one is active. Use before "
        "switching documents so you never edit the wrong one.",
        {"type": "object", "properties": {}},
        list_documents,
    ))

    def new_document(args):
        raw = bridge.new_document(args.get("label"))
        return _ok(f"created empty document {raw['label']} ({raw['name']})", raw=raw)

    reg.register(Tool(
        "new_document",
        "Create a blank document and make it active. Needed before generating "
        "into a session with nothing open - every other CAD tool requires an "
        "active document.",
        {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Document label, e.g. 'gripper_jaw'"}
            },
        },
        new_document,
        mutating=True,
        doc_mutating=True,
    ))

    def open_document(args):
        raw = bridge.open_document(args["path"])
        return _ok("opened %s (%d objects)" % (raw["label"], raw["object_count"]),
                   raw=raw)

    reg.register(Tool(
        "open_document",
        "Open an existing .FCStd file and make it active.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        open_document,
        mutating=True,
        doc_mutating=True,
    ))

    def activate_document(args):
        raw = bridge.activate_document(args["name"])
        return _ok(f"active document is now {raw['active']}", raw=raw)

    reg.register(Tool(
        "activate_document",
        "Switch the active document. Use the internal 'name' from "
        "list_documents, not the label.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        activate_document,
        mutating=True,
    ))

    def reload_document(args):
        raw = bridge.reload_document(args.get("name"))
        return _ok("reloaded %s from disk (%d objects)"
                   % (raw["name"], raw["object_count"]), raw=raw)

    reg.register(Tool(
        "reload_document",
        "Discard in-memory state and re-read the document from disk. Use when "
        "the file was changed outside FreeCAD. Fails on an unsaved document.",
        {"type": "object", "properties": {"name": {"type": "string"}}},
        reload_document,
        mutating=True,
        doc_mutating=True,
    ))

    def delete_object(args):
        names = args.get("names") or ([args["name"]] if args.get("name") else [])
        if not names:
            return _fail("Give 'name' or 'names' - which object should be deleted?")
        raw = bridge.delete_object(names, bool(args.get("cascade", False)))
        msg = "removed: " + (", ".join(raw["removed"]) or "nothing")
        if raw.get("failed"):
            msg += "\nfailed: " + json.dumps(raw["failed"])
        return _ok(msg, raw=raw)

    reg.register(Tool(
        "delete_object",
        "Delete objects from the document. Refuses by default if anything else "
        "depends on them (deleting a sketch under a pad breaks the pad) and "
        "tells you what the dependents are; pass cascade=true to remove those "
        "too. This is how you undo a mis-built feature.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "names": {"type": "array", "items": {"type": "string"}},
                "cascade": {
                    "type": "boolean",
                    "description": "Also delete every dependent object. Destructive.",
                },
            },
        },
        delete_object,
        mutating=True,
        destructive=True,
        doc_mutating=True,
    ))

    # ---- stock parts ----------------------------------------------------- #
    def list_library_parts(args):
        raw = bridge.list_library_parts(args.get("query"), int(args.get("limit") or 60))
        if not raw.get("roots"):
            return _ok(raw.get("hint", "no parts library configured"), raw=raw)
        parts = raw.get("parts", [])
        if not parts:
            return _ok("no library part matches %r" % (args.get("query") or ""), raw=raw)
        head = "%d match%s%s:" % (raw["count"], "" if raw["count"] == 1 else "es",
                                  " (truncated)" if raw.get("truncated") else "")
        return _ok(head + "\n" + "\n".join("  " + p["path"] for p in parts), raw=raw)

    reg.register(Tool(
        "list_library_parts",
        "Search the stock parts library (fasteners, bearings, profiles). Pass a "
        "query like 'M6' or 'bearing' to narrow it. Prefer a real library part "
        "over modelling a standard component from remembered dimensions.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring filter, e.g. 'M6' or 'hex'"},
                "limit": {"type": "integer"},
            },
        },
        list_library_parts,
    ))

    def insert_library_part(args):
        raw = bridge.insert_library_part(args["path"], args.get("label"))
        return _ok("inserted %s as %s" % (args["path"], raw.get("label")), raw=raw)

    reg.register(Tool(
        "insert_library_part",
        "Insert a stock part into the active document using the exact 'path' "
        "returned by list_library_parts.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from list_library_parts"},
                "label": {"type": "string"},
            },
            "required": ["path"],
        },
        insert_library_part,
        mutating=True,
        doc_mutating=True,
    ))

    return reg
