"""Conservative, stdlib-only URDF export for :mod:`assembly_graph`.

This module deliberately exports only the kinematic skeleton that is present
in an :class:`~orion_agent.harness.assembly_graph.AssemblyGraph`.  It never
guesses mass properties, visual meshes, collision meshes, joint axes, limits,
or frame transforms.  In particular, a joint must carry an explicit URDF
origin in its metadata before it can be exported::

    {
        "metadata": {
            "urdf_origin": {
                "xyz": [0, 0, 25],  # AssemblyGraph length units
                "rpy": [0, 0, 0],   # radians
            }
        }
    }

``AssemblyGraph`` supports broader assembly topologies than URDF.  This
exporter accepts only one connected, rooted kinematic tree so that it cannot
silently discard a loop, a second parent, or a disconnected subassembly.
Generated XML is intentionally a *kinematic-only* artifact.  It must still be
checked against controlled CAD, source data, and the target URDF parser.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Optional
from xml.etree import ElementTree as ET

from .assembly_graph import AssemblyGraph, Joint


_LENGTH_TO_METRES = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "millimetre": 0.001,
    "millimetres": 0.001,
}


class URDFExportError(ValueError):
    """Raised when an AssemblyGraph cannot be represented safely in URDF."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("URDF export validation failed:\n- " + "\n- ".join(self.errors))


def validate_urdf_export(graph: AssemblyGraph) -> list[str]:
    """Return deterministic export-safety errors without producing XML.

    The validation is deliberately stricter than
    :meth:`AssemblyGraph.validate <orion_agent.harness.assembly_graph.AssemblyGraph.validate>`:
    URDF needs a rooted tree, explicit joint transforms, and complete limits
    for every movable joint.  Joint origins must be authored at
    ``joint.metadata['urdf_origin']`` with both ``xyz`` and ``rpy`` vectors.
    ``xyz`` uses the graph's declared length units; ``rpy`` is in radians.
    """
    if not isinstance(graph, AssemblyGraph):
        return ["graph must be an AssemblyGraph instance"]

    errors = list(graph.validate())
    length_scale = _length_scale(graph.units)
    if length_scale is None:
        errors.append(
            f"unsupported AssemblyGraph units {graph.units!r}; URDF export supports mm or m"
        )

    parts_by_id = {part.id: part for part in graph.parts}
    interfaces_by_id = {interface.id: interface for interface in graph.interfaces}
    parent_by_child: dict[str, str] = {}
    children_by_parent: dict[str, list[str]] = {part_id: [] for part_id in parts_by_id}
    valid_edges: list[tuple[str, str]] = []

    for joint in graph.joints:
        parent_interface = interfaces_by_id.get(joint.parent_interface)
        child_interface = interfaces_by_id.get(joint.child_interface)
        label = f"joint {joint.id!r}"

        _validate_origin(joint, label, errors)
        if joint.kind in {"revolute", "prismatic"}:
            _validate_axis_and_limits(joint, label, errors)

        # ``AssemblyGraph.validate`` already reports bad references and
        # same-part joints.  Ignore those malformed edges here so topology
        # diagnostics remain meaningful and do not throw an implementation
        # exception for an in-progress graph.
        if parent_interface is None or child_interface is None:
            continue
        parent_link = parent_interface.part_id
        child_link = child_interface.part_id
        if parent_link not in parts_by_id or child_link not in parts_by_id:
            continue
        if parent_link == child_link:
            continue

        existing_parent = parent_by_child.get(child_link)
        if existing_parent is not None:
            errors.append(
                f"child link {child_link!r} is referenced by multiple parent joints "
                f"({existing_parent!r} and {joint.id!r})"
            )
        else:
            parent_by_child[child_link] = joint.id
        children_by_parent[parent_link].append(child_link)
        valid_edges.append((parent_link, child_link))

    _validate_tree(parts_by_id, valid_edges, parent_by_child, children_by_parent, errors)
    return _deduplicate(errors)


def export_urdf(graph: AssemblyGraph, *, robot_name: Optional[str] = None) -> str:
    """Export a validated :class:`AssemblyGraph` as a kinematic-only URDF.

    ``robot_name`` defaults to the graph ID.  The output contains one link per
    AssemblyGraph part instance and fixed, revolute, or prismatic joints.  It
    intentionally contains no visual, collision, transmission, or inertial
    elements because those values are not available in this IR.

    Raises:
        URDFExportError: if the graph is not a rooted tree or lacks evidence
            required to serialize its joints safely.
    """
    errors = validate_urdf_export(graph)
    if errors:
        raise URDFExportError(errors)

    name = graph.id if robot_name is None else robot_name
    if not isinstance(name, str) or not name.strip():
        raise URDFExportError(["robot_name must be a non-empty string"])
    name = name.strip()

    # Validation above establishes the supported unit conversion.
    length_scale = _length_scale(graph.units)
    assert length_scale is not None

    robot = ET.Element("robot", {"name": name})
    for part in graph.parts:
        ET.SubElement(robot, "link", {"name": part.id})

    interfaces_by_id = {interface.id: interface for interface in graph.interfaces}
    for joint in graph.joints:
        parent_interface = interfaces_by_id[joint.parent_interface]
        child_interface = interfaces_by_id[joint.child_interface]
        element = ET.SubElement(robot, "joint", {"name": joint.id, "type": joint.kind})

        origin = _origin_from_joint(joint)
        assert origin is not None  # guaranteed by validate_urdf_export
        xyz, rpy = origin
        ET.SubElement(
            element,
            "origin",
            {
                "xyz": _format_vector(tuple(component * length_scale for component in xyz)),
                "rpy": _format_vector(rpy),
            },
        )
        ET.SubElement(element, "parent", {"link": parent_interface.part_id})
        ET.SubElement(element, "child", {"link": child_interface.part_id})

        if joint.kind in {"revolute", "prismatic"}:
            axis = _numeric_vector(joint.axis)
            assert axis is not None  # guaranteed by validate_urdf_export
            ET.SubElement(element, "axis", {"xyz": _format_vector(axis)})

            limits = joint.limits
            assert limits is not None  # guaranteed by validate_urdf_export
            lower = limits.lower
            upper = limits.upper
            velocity = limits.velocity
            effort = limits.effort
            assert lower is not None and upper is not None and velocity is not None and effort is not None
            if joint.kind == "prismatic":
                lower *= length_scale
                upper *= length_scale
                velocity *= length_scale
            ET.SubElement(
                element,
                "limit",
                {
                    "lower": _format_number(lower),
                    "upper": _format_number(upper),
                    "effort": _format_number(effort),
                    "velocity": _format_number(velocity),
                },
            )

    ET.indent(robot, space="  ")
    body = ET.tostring(robot, encoding="unicode", short_empty_elements=True)
    warning = (
        "WARNING: Kinematic-only OrionFlow export from AssemblyGraph "
        f"{graph.id!r}. Source/provenance, revisions, frames, and physical "
        "properties require independent verification. Visual, collision, and "
        "inertial data are intentionally omitted; do not infer physical validity."
    )
    return f'<?xml version="1.0"?>\n<!-- {_xml_comment_text(warning)} -->\n{body}\n'


def _length_scale(units: Any) -> Optional[float]:
    if not isinstance(units, str):
        return None
    return _LENGTH_TO_METRES.get(units.strip().lower())


def _validate_origin(joint: Joint, label: str, errors: list[str]) -> None:
    origin = _origin_from_joint(joint)
    if origin is None:
        errors.append(
            f"{label} requires explicit metadata.urdf_origin with numeric xyz and rpy vectors"
        )
        return
    xyz, rpy = origin
    if not _is_nonempty_finite_vector(xyz):
        errors.append(f"{label} metadata.urdf_origin.xyz must be a finite three-number vector")
    if not _is_nonempty_finite_vector(rpy):
        errors.append(f"{label} metadata.urdf_origin.rpy must be a finite three-number vector")


def _validate_axis_and_limits(joint: Joint, label: str, errors: list[str]) -> None:
    axis = _numeric_vector(joint.axis)
    if axis is None or not any(abs(component) > 1e-12 for component in axis):
        errors.append(f"{label} ({joint.kind}) requires a non-zero finite axis")

    limits = joint.limits
    if limits is None:
        errors.append(
            f"{label} ({joint.kind}) requires numeric lower, upper, velocity, and effort limits"
        )
        return
    values = {
        "lower": limits.lower,
        "upper": limits.upper,
        "velocity": limits.velocity,
        "effort": limits.effort,
    }
    if any(_finite_number(value) is None for value in values.values()):
        errors.append(
            f"{label} ({joint.kind}) requires numeric lower, upper, velocity, and effort limits"
        )
        return

    lower = _finite_number(limits.lower)
    upper = _finite_number(limits.upper)
    velocity = _finite_number(limits.velocity)
    effort = _finite_number(limits.effort)
    assert lower is not None and upper is not None and velocity is not None and effort is not None
    if lower > upper:
        errors.append(f"{label} limits: lower must be less than or equal to upper")
    if velocity < 0:
        errors.append(f"{label} limits: velocity must be non-negative")
    if effort < 0:
        errors.append(f"{label} limits: effort must be non-negative")


def _validate_tree(
    parts_by_id: Mapping[str, Any],
    edges: Sequence[tuple[str, str]],
    parent_by_child: Mapping[str, str],
    children_by_parent: Mapping[str, Sequence[str]],
    errors: list[str],
) -> None:
    """Require the directed joint graph to be one rooted, connected tree."""
    part_ids = set(parts_by_id)
    if not part_ids:
        # AssemblyGraph validation already describes this condition.  Avoid a
        # misleading root count on top of it.
        return

    roots = sorted(part_ids - set(parent_by_child))
    if len(roots) != 1:
        rendered = ", ".join(repr(root) for root in roots) or "none"
        errors.append(
            f"URDF requires exactly one root link; found {len(roots)} ({rendered})"
        )

    expected_edge_count = len(part_ids) - 1
    if len(edges) != expected_edge_count:
        errors.append(
            f"URDF requires a tree with {expected_edge_count} joint edge(s) for "
            f"{len(part_ids)} link(s); found {len(edges)}"
        )

    if len(roots) != 1:
        return

    reachable: set[str] = set()
    stack = [roots[0]]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(reversed(sorted(children_by_parent.get(current, ()))))
    if reachable != part_ids:
        missing = ", ".join(repr(part_id) for part_id in sorted(part_ids - reachable))
        errors.append(
            f"URDF topology is not a rooted tree; link(s) unreachable from root "
            f"{roots[0]!r}: {missing}"
        )


def _origin_from_joint(
    joint: Joint,
) -> Optional[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Read a fully explicit URDF origin without ever defaulting a transform."""
    if not isinstance(joint.metadata, Mapping):
        return None
    raw_origin = joint.metadata.get("urdf_origin")
    if not isinstance(raw_origin, Mapping):
        return None
    xyz = _numeric_vector(raw_origin.get("xyz"))
    rpy = _numeric_vector(raw_origin.get("rpy"))
    if xyz is None or rpy is None:
        return None
    return xyz, rpy


def _numeric_vector(value: Any) -> Optional[tuple[float, float, float]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        return None
    vector = tuple(_finite_number(component) for component in value)
    if any(component is None for component in vector):
        return None
    return vector  # type: ignore[return-value]


def _is_nonempty_finite_vector(value: Sequence[float]) -> bool:
    return len(value) == 3 and all(_finite_number(component) is not None for component in value)


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_vector(vector: Sequence[float]) -> str:
    return " ".join(_format_number(component) for component in vector)


def _format_number(value: float) -> str:
    """Create deterministic URDF numeric attributes without negative zero."""
    if value == 0:
        return "0"
    return format(value, ".15g")


def _xml_comment_text(value: str) -> str:
    """Keep a comment safe even if graph identifiers contain comment syntax."""
    return value.replace("--", "- -").replace("\r", " ").replace("\n", " ")


def _deduplicate(errors: Sequence[str]) -> list[str]:
    """Preserve first-seen validation diagnostics while avoiding noise."""
    return list(dict.fromkeys(errors))


__all__ = ["URDFExportError", "validate_urdf_export", "export_urdf"]
