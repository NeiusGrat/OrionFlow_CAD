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


def build_registry(bridge, sandbox) -> ToolRegistry:
    """Construct the full tool surface bound to a bridge client and sandbox.

    ``bridge`` is a :class:`~orion_agent.harness.bridge_client.BridgeClient`;
    ``sandbox`` is a :class:`~orion_agent.harness.sandbox.SandboxManager`.
    """
    reg = ToolRegistry()

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

    def get_parameters(args):
        raw = bridge.get_object_parameters(args["name"])
        params = raw.get("parameters", {})
        keep = {k: v for k, v in params.items() if not k.startswith(("Visibility", "Shape"))}
        return _ok(json.dumps(keep, default=str)[:1500], raw=raw)

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
        return _ok(f"distance = {raw.get('distance')} mm", raw=raw)

    reg.register(Tool(
        "measure",
        "Measure the minimum distance between two sub-elements. Each ref is "
        "{name, sub} where sub is e.g. 'Face3', 'Edge5', 'Vertex2'.",
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

    # ---- write ---------------------------------------------------------- #
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
        return _ok(content, raw=result.to_dict(), artifacts=arts)

    reg.register(Tool(
        "write_code",
        "Execute Build123d Python in the sandbox. Assign the final solid to a "
        "variable named 'result'. Do NOT call export_step/export_stl yourself — "
        "the sandbox exports 'result' automatically and returns its topology and "
        "STEP/STL artifacts. Generated code runs isolated — never in FreeCAD.",
        {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Build123d python; assign the final solid to 'result'. "
                    "No export calls — the sandbox exports it for you.",
                },
                "exports": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["code"],
        },
        write_code,
        mutating=True,
    ))

    def import_shape(args):
        raw = bridge.import_shape(args["path"], args.get("label", "OrionResult"), args.get("replace"))
        return _ok(json.dumps(raw), raw=raw)

    reg.register(Tool(
        "import_shape",
        "Import a sandbox-produced STEP artifact into the live document, "
        "optionally replacing an existing object by name.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "label": {"type": "string"},
                "replace": {"type": "string"},
            },
            "required": ["path"],
        },
        import_shape,
        mutating=True,
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

    return reg
