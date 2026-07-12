"""Source-aware retrieval for OrionFlow's robotics assembly knowledge.

This module deliberately does not turn the robotics catalogue into a loose
RAG corpus.  It loads small versioned JSON records, validates cross references,
and keeps a record's data status (``source_specific``, ``candidate``, or
``illustrative``) in every response the agent sees.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional


_ROOT = Path(__file__).resolve().parents[1] / "knowledge" / "robotics"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_COLLECTIONS = {
    "component": ("components.json", "components"),
    "interface": ("interfaces.json", "interfaces"),
    "demo": ("demos.json", "demos"),
}
_DEMO_CUES = (
    ("linear axis", "robotics.demo.nema23_belt_linear_axis.v1"),
    ("belt driven axis", "robotics.demo.nema23_belt_linear_axis.v1"),
    ("parallel jaw", "robotics.demo.parallel_jaw_gripper.v1"),
    ("parallel gripper", "robotics.demo.parallel_jaw_gripper.v1"),
    ("pan tilt", "robotics.demo.pan_tilt_sensor_head.v1"),
    ("pan-tilt", "robotics.demo.pan_tilt_sensor_head.v1"),
    ("lidar head", "robotics.demo.pan_tilt_sensor_head.v1"),
    ("camera head", "robotics.demo.pan_tilt_sensor_head.v1"),
    ("harmonic actuator", "robotics.demo.modular_bldc_harmonic_actuator.v1"),
    ("strain wave actuator", "robotics.demo.modular_bldc_harmonic_actuator.v1"),
)


class RoboticsKnowledgeError(ValueError):
    """Raised for malformed or missing robotics knowledge requests."""


def _read(name: str) -> dict[str, Any]:
    try:
        with (_ROOT / name).open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RoboticsKnowledgeError(f"robotics knowledge asset missing: {name}") from exc
    except ValueError as exc:
        raise RoboticsKnowledgeError(f"robotics knowledge asset is invalid JSON: {name}") from exc


@lru_cache(maxsize=1)
def sources() -> dict[str, dict[str, Any]]:
    """Return all source records keyed by stable identifier."""
    data = _read("sources.json")
    return {record["id"]: dict(record) for record in data.get("sources", [])}


@lru_cache(maxsize=1)
def _collection(kind: str) -> tuple[dict[str, Any], ...]:
    if kind not in _COLLECTIONS:
        raise RoboticsKnowledgeError(f"unknown record kind: {kind}")
    filename, key = _COLLECTIONS[kind]
    data = _read(filename)
    records = data.get(key, [])
    if not isinstance(records, list):
        raise RoboticsKnowledgeError(f"{filename}: {key} must be an array")
    return tuple(dict(record) for record in records if isinstance(record, dict))


def components() -> tuple[dict[str, Any], ...]:
    return _collection("component")


def interfaces() -> tuple[dict[str, Any], ...]:
    return _collection("interface")


def demos() -> tuple[dict[str, Any], ...]:
    return _collection("demo")


def _id_index(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str) and record["id"]
    }


def validate_package() -> list[str]:
    """Return cross-reference integrity errors without external dependencies."""
    errors: list[str] = []
    source_ids = set(sources())
    component_index = _id_index(components())
    interface_index = _id_index(interfaces())
    demo_index = _id_index(demos())
    for kind, index in (
        ("component", component_index),
        ("interface", interface_index),
        ("demo", demo_index),
    ):
        records = _collection(kind)
        if len(index) != len(records):
            errors.append(f"{kind}: duplicate or missing record id")

    def check_source_refs(owner: str, record: dict[str, Any]) -> None:
        for source_id in record.get("sources", []) or []:
            if source_id not in source_ids:
                errors.append(f"{owner}: unknown source {source_id}")
        for fact in record.get("facts", []) or []:
            if isinstance(fact, dict) and fact.get("basis") == "source_specific":
                source_id = fact.get("source")
                if source_id not in source_ids:
                    errors.append(f"{owner}: fact {fact.get('name', '?')} has unknown source")

    for component in components():
        owner = f"component {component.get('id', '?')}"
        check_source_refs(owner, component)
        for interface_id in component.get("interfaces", []) or []:
            if interface_id not in interface_index:
                errors.append(f"{owner}: unknown interface {interface_id}")
    for interface in interfaces():
        check_source_refs(f"interface {interface.get('id', '?')}", interface)
    for demo in demos():
        owner = f"demo {demo.get('id', '?')}"
        check_source_refs(owner, demo)
        for component_id in demo.get("components", demo.get("component_ids", [])) or []:
            if component_id not in component_index:
                errors.append(f"{owner}: unknown component {component_id}")
        for interface_id in demo.get("interfaces", demo.get("interface_ids", [])) or []:
            if interface_id not in interface_index:
                errors.append(f"{owner}: unknown interface {interface_id}")
        graph_errors = validate_demo_graph(demo, component_index, interface_index)
        errors.extend(f"{owner}: {error}" for error in graph_errors)
    return errors


def get(kind: str, record_id: str) -> Optional[dict[str, Any]]:
    """Return one enriched record by kind and ID, or ``None`` when unknown."""
    if kind not in _COLLECTIONS:
        raise RoboticsKnowledgeError(f"kind must be one of: {', '.join(_COLLECTIONS)}")
    record = _id_index(_collection(kind)).get(record_id)
    return _enrich(kind, record) if record is not None else None


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_RE.findall(value.lower()))


def _searchable(record: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("id", "title", "kind", "summary", "agent_guidance", "description"):
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("tags", "components", "component_ids", "interfaces", "interface_ids"):
        value = record.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values)


def _enrich(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["record_kind"] = kind
    result["source_records"] = [
        dict(sources()[source_id])
        for source_id in record.get("sources", []) or []
        if source_id in sources()
    ]
    return result


def search(query: str, kind: str = "", limit: int = 6) -> list[dict[str, Any]]:
    """Search component, interface, and demo records deterministically."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    selected = (kind.strip().lower(),) if kind.strip() else tuple(_COLLECTIONS)
    invalid = [name for name in selected if name not in _COLLECTIONS]
    if invalid:
        raise RoboticsKnowledgeError(
            "kind must be component, interface, demo, or omitted"
        )
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for collection_kind in selected:
        for record in _collection(collection_kind):
            text = _searchable(record)
            score = len(query_tokens & _tokens(text))
            if query.lower() in str(record.get("title", "")).lower():
                score += 3
            if score:
                ranked.append((score, record.get("id", ""), _enrich(collection_kind, record)))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [record for _, _, record in ranked[:max(1, min(int(limit), 10))]]


def detect_intent(message: str, limit: int = 3) -> list[dict[str, Any]]:
    """Attach only high-confidence robotics demo candidates to an intent.

    This is intentionally conservative: it detects named mechanisms, never
    derives dimensions or selects a component. The agent must still retrieve the
    full record before using it.
    """
    text = message.lower()
    detected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cue, demo_id in _DEMO_CUES:
        if cue not in text or demo_id in seen:
            continue
        demo = get("demo", demo_id)
        if demo is None:
            continue
        detected.append({
            "kind": "robotics_demo_candidate",
            "demo_id": demo_id,
            "title": demo.get("title", demo_id),
            "data_status": demo.get("data_status", "not_classified"),
            "maturity": demo.get("maturity", "unknown"),
            "reason": f"request contains '{cue}'",
        })
        seen.add(demo_id)
        if len(detected) >= limit:
            break
    return detected


def demo_composition_graph(demo_id: str) -> dict[str, Any]:
    """Return a demo's high-level component/interface composition graph.

    This is intentionally *not* an :class:`AssemblyGraph`: it contains candidate
    components and relationships before exact part instances, coordinate frames,
    mates, and joint limits are known.  It becomes an AssemblyGraph only after
    those inputs are resolved.
    """
    demo = get("demo", demo_id)
    if demo is None:
        raise RoboticsKnowledgeError(f"unknown robotics demo: {demo_id}")
    graph = demo.get("assembly_graph", demo.get("assembly"))
    if not isinstance(graph, dict):
        raise RoboticsKnowledgeError(f"demo {demo_id} has no composition graph")
    return dict(graph)


def demo_assembly(demo_id: str) -> dict[str, Any]:
    """Compatibility alias for :func:`demo_composition_graph`.

    Callers must not interpret the returned composition graph as a mate-solved
    CAD AssemblyGraph.
    """
    return demo_composition_graph(demo_id)


def validate_demo_graph(
    demo: dict[str, Any],
    component_index: Optional[dict[str, dict[str, Any]]] = None,
    interface_index: Optional[dict[str, dict[str, Any]]] = None,
) -> list[str]:
    """Validate composition-graph references without pretending to solve mates."""
    component_index = component_index or _id_index(components())
    interface_index = interface_index or _id_index(interfaces())
    graph = demo.get("assembly_graph", demo.get("assembly"))
    if not isinstance(graph, dict):
        return ["missing composition graph"]
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes:
        return ["composition graph has no nodes"]
    if not isinstance(edges, list):
        return ["composition graph edges must be an array"]
    node_ids: set[str] = set()
    errors: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            errors.append("composition graph node has invalid id")
            continue
        if node["id"] in node_ids:
            errors.append(f"duplicate composition node {node['id']}")
        node_ids.add(node["id"])
        component_id = node.get("component_ref")
        if component_id not in component_index:
            errors.append(f"node {node['id']}: unknown component {component_id}")
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("composition graph edge must be an object")
            continue
        if edge.get("from") not in node_ids:
            errors.append(f"edge references unknown source node {edge.get('from')}")
        if edge.get("to") not in node_ids:
            errors.append(f"edge references unknown target node {edge.get('to')}")
        interface_id = edge.get("interface_ref")
        if interface_id not in interface_index:
            errors.append(f"edge {edge.get('from')}->{edge.get('to')}: unknown interface {interface_id}")
    return errors


def summarize_demo_topology(demo: dict[str, Any]) -> str:
    """Summarize a concept demo and enumerate its provenance/readiness boundary."""
    graph = demo_composition_graph(demo["id"])
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    kinematics = demo.get("kinematic_model", [])
    component_index = _id_index(components())
    statuses: dict[str, int] = {}
    for node in nodes:
        record = component_index.get(node.get("component_ref")) if isinstance(node, dict) else None
        status = record.get("data_status", "unknown") if record else "unknown"
        statuses[status] = statuses.get(status, 0) + 1
    status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    return (
        f"Concept composition graph: {len(nodes)} node(s), {len(edges)} relationship(s), "
        f"{len(kinematics)} kinematic intent record(s). Component status: {status_text or 'none'}.\n"
        "Before generating a CAD AssemblyGraph: select exact part numbers/revisions, "
        "instantiate physical parts, declare coordinate frames and mates, and define "
        "numeric joint limits."
    )


def render(records: list[dict[str, Any]]) -> str:
    """Render source and review status prominently for LLM tool observations."""
    lines: list[str] = []
    for record in records:
        status = record.get("data_status", "not_classified")
        review = record.get("engineering_review", "required")
        lines.append(
            f"- [{record['record_kind']}] {record.get('title', record.get('id'))} "
            f"({record.get('id')}; data_status={status}; engineering_review={review}): "
            f"{record.get('summary', record.get('description', ''))}"
        )
        required = record.get("required_selection_inputs", [])
        if required:
            lines.append("  Required before release: " + "; ".join(required))
        guidance = record.get("agent_guidance")
        if guidance:
            lines.append("  Agent guidance: " + guidance)
        source_text = "; ".join(
            f"{source['title']} [{source['kind']}]"
            for source in record.get("source_records", [])
        )
        if source_text:
            lines.append("  Sources: " + source_text)
    return "\n".join(lines)


def render_demo_manifest(demo: dict[str, Any], topology_summary: str) -> str:
    """Render a demo record plus its validated composition-graph summary."""
    text = render([demo])
    exports = demo.get("exports", demo.get("expected_exports", []))
    gates = demo.get("verification_gates", demo.get("evidence_gates", []))
    if exports:
        text += "\n  Expected artifacts: " + ", ".join(str(item) for item in exports)
    if gates:
        text += "\n  Evidence gates: " + "; ".join(str(item) for item in gates)
    return text + "\n" + topology_summary


__all__ = [
    "RoboticsKnowledgeError",
    "sources",
    "components",
    "interfaces",
    "demos",
    "validate_package",
    "get",
    "search",
    "detect_intent",
    "demo_composition_graph",
    "demo_assembly",
    "validate_demo_graph",
    "summarize_demo_topology",
    "render",
    "render_demo_manifest",
]
