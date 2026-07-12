"""Compile a validated AssemblyGraph into a native FreeCAD link assembly.

The harness owns the AssemblyGraph contract; this adapter owns only the
FreeCAD occurrence tree.  It deliberately does *not* solve arbitrary mate
graphs.  A compilation request must describe one directed, rooted kinematic
tree and bind every AssemblyGraph part instance to an existing FreeCAD source
object whose placement is identity.  This prevents an already-positioned
source object from silently contributing an additional transform.

The placement convention is explicit and intentionally small::

    T_child = T_parent * F_parent * J(axis, value) * inverse(F_child)

``F_parent`` and ``F_child`` are local interface frames.  A revolute value is
in radians; a prismatic value is in the graph's declared length units.  The
joint axis is expressed in the parent interface frame.  Fixed joints have the
identity motion.  This module creates an ``App::Part`` containing one
``App::Link`` per part occurrence, leaving source objects unmodified.

FreeCAD is imported only inside :func:`compile_assembly_graph`, so importing
this module remains safe in the agent process and ordinary unit tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Optional


COMPILER_VERSION = "orion_assembly_link_compiler_v1"
PLACEMENT_FORMULA = "T_child = T_parent * F_parent * J(axis, value) * inverse(F_child)"
_EPSILON = 1e-9


class AssemblyCompilationError(RuntimeError):
    """Raised when an AssemblyGraph cannot safely become a FreeCAD assembly.

    ``errors`` retains individual preflight diagnostics for API callers while
    the exception text remains immediately useful in FreeCAD's report view.
    """

    def __init__(self, message: str, errors: Optional[Sequence[str]] = None) -> None:
        self.errors = tuple(errors or ())
        if self.errors and "\n- " not in message:
            message = message.rstrip() + "\n- " + "\n- ".join(self.errors)
        super().__init__(message)


# A short alias makes the error easy to discover for callers that use the
# module name rather than the public function name.
AssemblyCompilerError = AssemblyCompilationError


@dataclass(frozen=True)
class _Transform:
    """A rigid transform represented independently of the FreeCAD API."""

    rotation: tuple[tuple[float, float, float], ...]
    translation: tuple[float, float, float]

    @classmethod
    def identity(cls) -> "_Transform":
        return cls(
            rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            translation=(0.0, 0.0, 0.0),
        )

    def compose(self, other: "_Transform") -> "_Transform":
        rotation = _matrix_multiply(self.rotation, other.rotation)
        translated = _matrix_vector(self.rotation, other.translation)
        return _Transform(
            rotation=rotation,
            translation=tuple(
                self.translation[index] + translated[index] for index in range(3)
            ),
        )

    def inverse(self) -> "_Transform":
        rotation = _transpose(self.rotation)
        negated = tuple(-component for component in self.translation)
        return _Transform(rotation=rotation, translation=_matrix_vector(rotation, negated))

    def as_json(self) -> dict[str, list[list[float]] | list[float]]:
        return {
            "translation": [_clean_number(value) for value in self.translation],
            "rotation_matrix": [
                [_clean_number(value) for value in row] for row in self.rotation
            ],
        }


@dataclass(frozen=True)
class _JointPlacement:
    """Preflight information needed to create one link occurrence."""

    joint: Any
    parent_part_id: str
    child_part_id: str
    value: float
    axis: Optional[tuple[float, float, float]]
    transform: _Transform


def compile_assembly_graph(
    graph_data: Any,
    bindings: Mapping[str, Any],
    root_part_id: str,
    joint_values: Optional[Mapping[str, Any]] = None,
    label: Optional[str] = None,
    doc: Any = None,
) -> dict[str, Any]:
    """Compile a validated rooted AssemblyGraph to an ``App::Part`` of links.

    Args:
        graph_data: An existing validated ``AssemblyGraph`` instance, or the
            JSON-like input accepted by ``parse_assembly_graph``.  Raw data is
            parsed strictly before any FreeCAD mutation.
        bindings: A mapping from every ``part.id`` to an existing object in
            ``doc``.  A binding may be a source object's Name, the object
            itself, or a mapping containing ``object``/``object_name``.
        root_part_id: The directed tree's only root part occurrence.  Its link
            is placed at the assembly origin.
        joint_values: Values for every movable joint.  Values are radians for
            revolute joints and graph length units for prismatic joints.  If
            ``None``, every movable joint is evaluated at zero only when zero
            satisfies its declared limits, and a warning is returned.
        label: Optional human-facing label for the new ``App::Part``.
        doc: Existing FreeCAD document.  Defaults to ``FreeCAD.ActiveDocument``.

    Returns:
        A JSON-safe compilation report.  It intentionally contains object
        names instead of FreeCAD objects, so it can cross the bridge boundary.

    Raises:
        AssemblyCompilationError: on invalid graph/input, non-tree topology,
            unsafe source placement, limits violation, or a FreeCAD mutation
            failure.  Any objects created by this call are removed on failure.

    The caller owns document recomputation.  The compiler never calls
    ``doc.recompute()`` because bridge capabilities often batch mutations.
    """

    graph = _validated_graph(graph_data)
    app = _freecad_module()
    target_doc = _resolve_document(app, doc)
    parts = tuple(_items(graph, "parts"))
    interfaces = tuple(_items(graph, "interfaces"))
    joints = tuple(_items(graph, "joints"))

    graph_id = _text(_field(graph, "id"), "AssemblyGraph.id")
    graph_units = _text(_field(graph, "units", "mm"), "AssemblyGraph.units")
    part_by_id = _index_by_id(parts, "part instance")
    interface_by_id = _index_by_id(interfaces, "interface")
    joint_by_id = _index_by_id(joints, "joint")

    errors: list[str] = []
    root_id = _text(root_part_id, "root_part_id", errors)
    if root_id not in part_by_id:
        errors.append(f"root_part_id {root_id!r} is not an AssemblyGraph part instance")

    source_by_part = _preflight_bindings(
        bindings, part_by_id, target_doc, errors
    )
    normalized_values, value_warnings = _preflight_joint_values(
        joints, joint_by_id, joint_values, errors
    )
    topology = _preflight_tree(
        joints,
        part_by_id,
        interface_by_id,
        root_id,
        normalized_values,
        errors,
    )

    assembly_label = _assembly_label(graph, label, errors)
    planned_names = _planned_object_names(graph_id, parts)
    _preflight_name_collisions(target_doc, planned_names, errors)

    # Ensure the graph can be persisted as provenance before any object exists.
    graph_json = _json_text(_graph_json_data(graph), "AssemblyGraph provenance", errors)
    values_json = _json_text(normalized_values, "joint value provenance", errors)
    if errors:
        raise AssemblyCompilationError("Assembly compilation preflight failed", errors)

    # Type narrowing for the rest of the function: preflight must construct a
    # transform for every part in a successful directed tree.
    assert topology is not None
    assert source_by_part is not None
    assert graph_json is not None
    assert values_json is not None

    created: list[str] = []
    assembly = None
    try:
        assembly = target_doc.addObject("App::Part", planned_names["assembly"])
        _require_object(assembly, "FreeCAD did not create the App::Part")
        created.append(_object_name(assembly))
        assembly.Label = assembly_label
        _write_assembly_provenance(
            assembly,
            graph_id=graph_id,
            graph_units=graph_units,
            root_part_id=root_id,
            graph_json=graph_json,
            values_json=values_json,
        )

        instances: list[dict[str, Any]] = []
        links_by_part: dict[str, Any] = {}
        for part in parts:
            part_id = _text(_field(part, "id"), "part instance.id")
            link = _new_link(target_doc, assembly, planned_names[part_id])
            _require_object(link, f"FreeCAD did not create link for part {part_id!r}")
            created.append(_object_name(link))

            source = source_by_part[part_id]
            link.LinkedObject = source
            _enable_link_transform(link)
            transform = topology["transforms"][part_id]
            link.Placement = _freecad_placement(app, transform)
            link.Label = _instance_label(part)
            incoming = topology["incoming"].get(part_id)
            _write_instance_provenance(
                link,
                part=part,
                source=source,
                parent_joint_id=_field(incoming.joint, "id") if incoming else "",
            )
            links_by_part[part_id] = link
            instances.append(
                _instance_result(part, source, link, transform, incoming)
            )

        joints_result = [
            _joint_result(joint_placement, graph_units)
            for joint_placement in topology["joint_order"]
        ]
        result = {
            "status": "compiled",
            "compiler": COMPILER_VERSION,
            "placement_formula": PLACEMENT_FORMULA,
            "assembly": {
                "name": _object_name(assembly),
                "label": _object_label(assembly),
                "type_id": _object_type_id(assembly),
                "assembly_id": graph_id,
                "root_part_id": root_id,
                "units": graph_units,
            },
            "created": list(created),
            "instances": instances,
            "joints": joints_result,
            "joint_values": dict(normalized_values),
            "bom": _json_bom(graph),
            "warnings": value_warnings,
        }
        # This is deliberately a validation check rather than serialization
        # output: object references must never leak across the bridge.
        json.dumps(result, allow_nan=False, sort_keys=True)
        return result
    except AssemblyCompilationError:
        _cleanup_created(target_doc, created)
        raise
    except Exception as exc:  # noqa: BLE001 - FreeCAD exceptions vary by build.
        _cleanup_created(target_doc, created)
        raise AssemblyCompilationError(
            "FreeCAD assembly compilation failed; newly created objects were removed: "
            + str(exc)
        ) from exc


def _validated_graph(graph_data: Any) -> Any:
    """Use the harness parser lazily only when raw authoring data is supplied."""

    candidate = graph_data
    if not callable(getattr(candidate, "validate", None)):
        try:
            from orion_agent.harness.assembly_graph import parse_assembly_graph
        except Exception as exc:  # noqa: BLE001 - addon can be distributed alone.
            raise AssemblyCompilationError(
                "graph_data must be a validated AssemblyGraph instance; raw graph "
                "data requires OrionFlow's assembly_graph parser"
            ) from exc
        try:
            candidate = parse_assembly_graph(graph_data, strict=True)
        except Exception as exc:  # noqa: BLE001 - preserve a bridge-safe message.
            raise AssemblyCompilationError(f"AssemblyGraph parsing failed: {exc}") from exc

    try:
        errors = list(candidate.validate())
    except Exception as exc:  # noqa: BLE001
        raise AssemblyCompilationError(
            "graph_data must be a validated AssemblyGraph-compatible object"
        ) from exc
    if errors:
        raise AssemblyCompilationError("AssemblyGraph validation failed", errors)
    for attribute in ("id", "parts", "interfaces", "joints"):
        if not hasattr(candidate, attribute):
            raise AssemblyCompilationError(
                f"AssemblyGraph-compatible object is missing required attribute {attribute!r}"
            )
    return candidate


def _freecad_module() -> Any:
    try:
        import FreeCAD as App  # type: ignore
    except ImportError as exc:
        raise AssemblyCompilationError(
            "FreeCAD is unavailable. Run compile_assembly_graph inside FreeCAD "
            "or freecadcmd."
        ) from exc
    return App


def _resolve_document(app: Any, doc: Any) -> Any:
    target = doc if doc is not None else getattr(app, "ActiveDocument", None)
    if target is None:
        raise AssemblyCompilationError(
            "No FreeCAD document was supplied and there is no active document"
        )
    if not callable(getattr(target, "addObject", None)) or not callable(
        getattr(target, "getObject", None)
    ):
        raise AssemblyCompilationError("doc must be a live FreeCAD document")
    return target


def _items(graph: Any, name: str) -> Sequence[Any]:
    value = _field(graph, name)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AssemblyCompilationError(f"AssemblyGraph.{name} must be a sequence")
    return value


def _index_by_id(items: Sequence[Any], noun: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    errors: list[str] = []
    for item in items:
        item_id = _text(_field(item, "id"), f"{noun}.id", errors)
        if item_id in result:
            errors.append(f"duplicate {noun} id {item_id!r}")
        result[item_id] = item
    if errors:
        raise AssemblyCompilationError("AssemblyGraph identity preflight failed", errors)
    return result


def _preflight_bindings(
    bindings: Mapping[str, Any],
    part_by_id: Mapping[str, Any],
    doc: Any,
    errors: list[str],
) -> Optional[dict[str, Any]]:
    if not isinstance(bindings, Mapping):
        errors.append("bindings must be a mapping from part instance id to source object")
        return None

    supplied = set(bindings)
    expected = set(part_by_id)
    missing = sorted(expected - supplied)
    extra = sorted(str(key) for key in supplied - expected)
    if missing:
        errors.append("missing source binding(s): " + ", ".join(repr(item) for item in missing))
    if extra:
        errors.append("unknown source binding(s): " + ", ".join(repr(item) for item in extra))

    result: dict[str, Any] = {}
    for part_id in sorted(expected):
        if part_id not in bindings:
            continue
        try:
            source = _resolve_source_object(bindings[part_id], doc, part_id)
        except AssemblyCompilationError as exc:
            errors.append(str(exc))
            continue
        result[part_id] = source
    return result if not missing and not extra and len(result) == len(expected) else None


def _resolve_source_object(binding: Any, doc: Any, part_id: str) -> Any:
    candidate = binding
    if isinstance(binding, Mapping):
        candidates = [
            binding[key]
            for key in ("object", "object_name", "source_object")
            if key in binding
        ]
        if len(candidates) != 1:
            raise AssemblyCompilationError(
                f"binding for part {part_id!r} must contain exactly one of "
                "'object', 'object_name', or 'source_object'"
            )
        candidate = candidates[0]

    if isinstance(candidate, str):
        if not candidate.strip():
            raise AssemblyCompilationError(f"binding for part {part_id!r} has an empty object name")
        candidate = doc.getObject(candidate.strip())
    if candidate is None:
        raise AssemblyCompilationError(
            f"binding for part {part_id!r} does not resolve to an object in the target document"
        )

    source_name = getattr(candidate, "Name", None)
    if not isinstance(source_name, str) or not source_name:
        raise AssemblyCompilationError(
            f"binding for part {part_id!r} is not a named FreeCAD source object"
        )
    source_doc = getattr(candidate, "Document", None)
    if source_doc is not doc:
        raise AssemblyCompilationError(
            f"source object {source_name!r} for part {part_id!r} is not in the target document"
        )
    if doc.getObject(source_name) is None:
        raise AssemblyCompilationError(
            f"source object {source_name!r} for part {part_id!r} is not present in the target document"
        )
    if not hasattr(candidate, "Placement"):
        raise AssemblyCompilationError(
            f"source object {source_name!r} for part {part_id!r} has no Placement"
        )
    if not _placement_is_identity(candidate.Placement):
        raise AssemblyCompilationError(
            f"source object {source_name!r} for part {part_id!r} must have identity "
            "Placement before it can be linked into an assembly"
        )
    return candidate


def _preflight_joint_values(
    joints: Sequence[Any],
    joint_by_id: Mapping[str, Any],
    joint_values: Optional[Mapping[str, Any]],
    errors: list[str],
) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    if joint_values is None:
        raw_values: Mapping[str, Any] = {}
        use_zero_defaults = True
    elif isinstance(joint_values, Mapping):
        raw_values = joint_values
        use_zero_defaults = False
    else:
        errors.append("joint_values must be a mapping or None")
        return {}, warnings

    unknown = sorted(str(key) for key in set(raw_values) - set(joint_by_id))
    if unknown:
        errors.append("joint_values contains unknown joint id(s): " + ", ".join(repr(item) for item in unknown))

    normalized: dict[str, float] = {}
    for joint in joints:
        joint_id = _text(_field(joint, "id"), "joint.id", errors)
        kind = _text(_field(joint, "kind"), f"joint {joint_id!r}.kind", errors).lower()
        is_movable = kind in {"revolute", "prismatic"}
        if joint_id in raw_values:
            value = _number(raw_values[joint_id], f"joint_values[{joint_id!r}]", errors)
        elif is_movable and use_zero_defaults:
            value = 0.0
            warnings.append(
                f"joint {joint_id!r} was evaluated at implicit zero because joint_values was omitted"
            )
        elif is_movable:
            errors.append(f"joint_values must explicitly include movable joint {joint_id!r}")
            continue
        else:
            value = 0.0

        if kind == "fixed" and abs(value) > _EPSILON:
            errors.append(f"fixed joint {joint_id!r} must have a value of 0")
        if is_movable:
            _validate_joint_limits(joint, joint_id, value, errors)
        normalized[joint_id] = value
    return normalized, warnings


def _validate_joint_limits(joint: Any, joint_id: str, value: float, errors: list[str]) -> None:
    limits = _field(joint, "limits", None)
    if limits is None:
        return
    lower = _field(limits, "lower", None)
    upper = _field(limits, "upper", None)
    if lower is None and upper is None:
        return
    if lower is None or upper is None:
        errors.append(f"joint {joint_id!r} limits must provide both lower and upper")
        return
    low = _number(lower, f"joint {joint_id!r}.limits.lower", errors)
    high = _number(upper, f"joint {joint_id!r}.limits.upper", errors)
    if low > high:
        errors.append(f"joint {joint_id!r} limits lower must be less than or equal to upper")
        return
    if value < low - _EPSILON or value > high + _EPSILON:
        errors.append(
            f"joint value {value:g} for {joint_id!r} is outside declared limits [{low:g}, {high:g}]"
        )


def _preflight_tree(
    joints: Sequence[Any],
    part_by_id: Mapping[str, Any],
    interface_by_id: Mapping[str, Any],
    root_id: str,
    joint_values: Mapping[str, float],
    errors: list[str],
) -> Optional[dict[str, Any]]:
    """Require one directed root and calculate all occurrence transforms."""

    if root_id not in part_by_id:
        return None
    if len(joints) != len(part_by_id) - 1:
        errors.append(
            f"assembly compiler requires a tree with {len(part_by_id) - 1} joint(s) "
            f"for {len(part_by_id)} part instance(s); found {len(joints)}"
        )

    children: dict[str, list[_JointPlacement]] = {part_id: [] for part_id in part_by_id}
    incoming: dict[str, _JointPlacement] = {}
    invalid_topology = False
    for joint in joints:
        joint_id = _text(_field(joint, "id"), "joint.id", errors)
        parent_interface_id = _text(
            _field(joint, "parent_interface"), f"joint {joint_id!r}.parent_interface", errors
        )
        child_interface_id = _text(
            _field(joint, "child_interface"), f"joint {joint_id!r}.child_interface", errors
        )
        parent_interface = interface_by_id.get(parent_interface_id)
        child_interface = interface_by_id.get(child_interface_id)
        if parent_interface is None or child_interface is None:
            errors.append(f"joint {joint_id!r} has unresolved interface references")
            invalid_topology = True
            continue
        parent_id = _text(
            _field(parent_interface, "part_id"),
            f"interface {parent_interface_id!r}.part_id",
            errors,
        )
        child_id = _text(
            _field(child_interface, "part_id"),
            f"interface {child_interface_id!r}.part_id",
            errors,
        )
        if parent_id not in part_by_id or child_id not in part_by_id:
            errors.append(f"joint {joint_id!r} references an interface on an unknown part")
            invalid_topology = True
            continue
        if parent_id == child_id:
            errors.append(f"joint {joint_id!r} connects a part instance to itself")
            invalid_topology = True
            continue
        if child_id in incoming:
            other = _text(_field(incoming[child_id].joint, "id"), "joint.id")
            errors.append(
                f"part instance {child_id!r} has multiple parent joints ({other!r} and {joint_id!r})"
            )
            invalid_topology = True
            continue

        try:
            parent_frame = _frame_transform(_field(parent_interface, "frame"), parent_interface_id)
            child_frame = _frame_transform(_field(child_interface, "frame"), child_interface_id)
            kind = _text(_field(joint, "kind"), f"joint {joint_id!r}.kind").lower()
            value = joint_values[joint_id]
            axis = _joint_axis(joint, joint_id) if kind in {"revolute", "prismatic"} else None
            motion = _joint_motion(kind, axis, value, joint_id)
        except AssemblyCompilationError as exc:
            errors.append(str(exc))
            invalid_topology = True
            continue

        # The transform is completed once the parent occurrence is visited.
        placeholder = _JointPlacement(
            joint=joint,
            parent_part_id=parent_id,
            child_part_id=child_id,
            value=value,
            axis=axis,
            transform=parent_frame.compose(motion).compose(child_frame.inverse()),
        )
        children[parent_id].append(placeholder)
        incoming[child_id] = placeholder

    roots = sorted(set(part_by_id) - set(incoming))
    if roots != [root_id]:
        rendered = ", ".join(repr(item) for item in roots) or "none"
        errors.append(
            f"assembly compiler requires root_part_id {root_id!r} to be the only directed "
            f"root; found {rendered}"
        )
        invalid_topology = True
    if root_id in incoming:
        errors.append(f"root part instance {root_id!r} must not have a parent joint")
        invalid_topology = True
    if invalid_topology or errors:
        return None

    transforms: dict[str, _Transform] = {root_id: _Transform.identity()}
    ordered: list[_JointPlacement] = []
    stack = [root_id]
    while stack:
        parent_id = stack.pop()
        parent_transform = transforms[parent_id]
        # Reverse push keeps traversal in original joint declaration order.
        for template in reversed(children[parent_id]):
            child_id = template.child_part_id
            if child_id in transforms:
                errors.append(
                    f"assembly graph has a directed cycle involving part instance {child_id!r}"
                )
                continue
            transform = parent_transform.compose(template.transform)
            placement = _JointPlacement(
                joint=template.joint,
                parent_part_id=template.parent_part_id,
                child_part_id=child_id,
                value=template.value,
                axis=template.axis,
                transform=transform,
            )
            transforms[child_id] = transform
            incoming[child_id] = placement
            ordered.append(placement)
            stack.append(child_id)
    if set(transforms) != set(part_by_id):
        missing = sorted(set(part_by_id) - set(transforms))
        errors.append(
            "assembly compiler requires every part to be reachable from root "
            f"{root_id!r}; unreachable: " + ", ".join(repr(item) for item in missing)
        )
        return None
    if errors:
        return None
    return {"transforms": transforms, "incoming": incoming, "joint_order": ordered}


def _frame_transform(frame: Any, interface_id: str) -> _Transform:
    if frame is None:
        raise AssemblyCompilationError(
            f"interface {interface_id!r} must provide an explicit local frame"
        )
    origin = _vector(_field(frame, "origin", (0.0, 0.0, 0.0)), f"interface {interface_id!r}.frame.origin")
    x_axis = _field(frame, "x_axis", None)
    z_axis = _field(frame, "z_axis", None)
    if x_axis is None and z_axis is None:
        return _Transform.identity().with_translation(origin)
    if x_axis is None or z_axis is None:
        raise AssemblyCompilationError(
            f"interface {interface_id!r} frame must define x_axis and z_axis together "
            "or omit both for an identity orientation"
        )
    x = _normalise(_vector(x_axis, f"interface {interface_id!r}.frame.x_axis"), "x_axis")
    z = _normalise(_vector(z_axis, f"interface {interface_id!r}.frame.z_axis"), "z_axis")
    # Preserve the authored Z direction.  Orthogonalize X so FreeCAD receives
    # a proper right-handed rotation even when authoring data has rounding noise.
    projected_x = tuple(x[index] - _dot(x, z) * z[index] for index in range(3))
    x = _normalise(projected_x, "frame x_axis perpendicular to z_axis")
    y = _normalise(_cross(z, x), "frame y_axis")
    x = _cross(y, z)
    return _Transform(
        rotation=(
            (x[0], y[0], z[0]),
            (x[1], y[1], z[1]),
            (x[2], y[2], z[2]),
        ),
        translation=origin,
    )


def _joint_axis(joint: Any, joint_id: str) -> tuple[float, float, float]:
    axis = _field(joint, "axis", None)
    if axis is None:
        raise AssemblyCompilationError(f"movable joint {joint_id!r} requires a non-zero axis")
    return _normalise(_vector(axis, f"joint {joint_id!r}.axis"), f"joint {joint_id!r}.axis")


def _joint_motion(
    kind: str,
    axis: Optional[tuple[float, float, float]],
    value: float,
    joint_id: str,
) -> _Transform:
    if kind == "fixed":
        return _Transform.identity()
    if axis is None:
        raise AssemblyCompilationError(f"movable joint {joint_id!r} requires a non-zero axis")
    if kind == "prismatic":
        return _Transform(
            rotation=_Transform.identity().rotation,
            translation=tuple(component * value for component in axis),
        )
    if kind == "revolute":
        return _Transform(rotation=_axis_angle_matrix(axis, value), translation=(0.0, 0.0, 0.0))
    raise AssemblyCompilationError(
        f"joint {joint_id!r} has unsupported kind {kind!r}; expected fixed, revolute, or prismatic"
    )


def _planned_object_names(graph_id: str, parts: Sequence[Any]) -> dict[str, str]:
    planned: dict[str, str] = {"assembly": _freecad_name("OrionAssembly_" + graph_id)}
    used = set(planned.values())
    for index, part in enumerate(parts, start=1):
        part_id = _text(_field(part, "id"), "part instance.id")
        base = _freecad_name(f"{planned['assembly']}_{part_id}")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = _freecad_name(f"{base}_{suffix}")
            suffix += 1
        # A malformed graph cannot reach here after validation, but this keeps
        # a direct object caller from silently overwriting the plan dictionary.
        if part_id in planned:
            candidate = _freecad_name(f"{candidate}_{index}")
        planned[part_id] = candidate
        used.add(candidate)
    return planned


def _preflight_name_collisions(doc: Any, planned_names: Mapping[str, str], errors: list[str]) -> None:
    for name in planned_names.values():
        if doc.getObject(name) is not None:
            errors.append(
                f"cannot create assembly occurrence {name!r}: an object with that Name already exists"
            )


def _assembly_label(graph: Any, label: Optional[str], errors: list[str]) -> str:
    if label is not None:
        return _text(label, "label", errors)
    name = _field(graph, "name", "")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return _text(_field(graph, "id"), "AssemblyGraph.id", errors)


def _graph_json_data(graph: Any) -> Any:
    to_dict = getattr(graph, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    # A graph-like object without to_dict is accepted for compilation but its
    # provenance must still remain auditable.  Its stable minimum is enough.
    return {
        "id": _field(graph, "id"),
        "units": _field(graph, "units", "mm"),
        "parts": [_plain_item(item) for item in _items(graph, "parts")],
        "interfaces": [_plain_item(item) for item in _items(graph, "interfaces")],
        "joints": [_plain_item(item) for item in _items(graph, "joints")],
    }


def _plain_item(item: Any) -> Any:
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(item, Mapping):
        return dict(item)
    return dict(getattr(item, "__dict__", {}))


def _json_text(value: Any, description: str, errors: list[str]) -> Optional[str]:
    try:
        return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        errors.append(f"{description} is not JSON-safe: {exc}")
        return None


def _new_link(doc: Any, assembly: Any, name: str) -> Any:
    creator = getattr(assembly, "newObject", None)
    if callable(creator):
        return creator("App::Link", name)
    link = doc.addObject("App::Link", name)
    adder = getattr(assembly, "addObject", None)
    if not callable(adder):
        raise AssemblyCompilationError("created App::Part cannot contain App::Link objects")
    adder(link)
    return link


def _enable_link_transform(link: Any) -> None:
    try:
        link.LinkTransform = True
    except Exception as exc:  # noqa: BLE001
        raise AssemblyCompilationError(
            f"App::Link {_object_name(link)!r} does not support LinkTransform"
        ) from exc


def _freecad_placement(app: Any, transform: _Transform) -> Any:
    x_axis = app.Vector(
        transform.rotation[0][0], transform.rotation[1][0], transform.rotation[2][0]
    )
    y_axis = app.Vector(
        transform.rotation[0][1], transform.rotation[1][1], transform.rotation[2][1]
    )
    z_axis = app.Vector(
        transform.rotation[0][2], transform.rotation[1][2], transform.rotation[2][2]
    )
    try:
        rotation = app.Rotation(x_axis, y_axis, z_axis, "ZXY")
    except Exception as exc:  # noqa: BLE001
        raise AssemblyCompilationError(
            "FreeCAD could not construct a rotation from the local interface frames"
        ) from exc
    base = app.Vector(*transform.translation)
    return app.Placement(base, rotation)


def _write_assembly_provenance(
    assembly: Any,
    *,
    graph_id: str,
    graph_units: str,
    root_part_id: str,
    graph_json: str,
    values_json: str,
) -> None:
    _set_string_property(assembly, "OrionAssemblyId", graph_id, "AssemblyGraph identifier")
    _set_string_property(assembly, "OrionCompiler", COMPILER_VERSION, "Assembly compiler version")
    _set_string_property(assembly, "OrionUnits", graph_units, "AssemblyGraph length units")
    _set_string_property(assembly, "OrionRootPartId", root_part_id, "Root part instance id")
    _set_string_property(
        assembly,
        "OrionPlacementFormula",
        PLACEMENT_FORMULA,
        "Occurrence placement convention",
    )
    _set_string_property(assembly, "OrionAssemblyGraph", graph_json, "Canonical AssemblyGraph JSON")
    _set_string_property(assembly, "OrionJointValues", values_json, "Applied joint values JSON")


def _write_instance_provenance(
    link: Any,
    *,
    part: Any,
    source: Any,
    parent_joint_id: Any,
) -> None:
    part_id = _text(_field(part, "id"), "part instance.id")
    _set_string_property(link, "OrionPartInstanceId", part_id, "AssemblyGraph part instance id")
    _set_string_property(
        link,
        "OrionPartNumber",
        _text(_field(part, "part_number"), f"part {part_id!r}.part_number"),
        "Source part number",
    )
    _set_string_property(link, "OrionRevision", _string_or_empty(_field(part, "revision", "")), "Source revision")
    _set_string_property(
        link,
        "OrionManufacturer",
        _string_or_empty(_field(part, "manufacturer", "")),
        "Source manufacturer",
    )
    _set_string_property(link, "OrionSourceObject", _object_name(source), "Linked source object Name")
    _set_string_property(
        link,
        "OrionSourceDocument",
        _object_name(getattr(source, "Document", None)),
        "Linked source document Name",
    )
    _set_string_property(
        link,
        "OrionParentJointId",
        _string_or_empty(parent_joint_id),
        "Incoming AssemblyGraph joint id",
    )
    _set_string_property(
        link,
        "OrionPlacementFormula",
        PLACEMENT_FORMULA,
        "Occurrence placement convention",
    )


def _set_string_property(obj: Any, name: str, value: str, description: str) -> None:
    properties = getattr(obj, "PropertiesList", ())
    if name not in properties:
        obj.addProperty("App::PropertyString", name, "OrionFlow", description)
    setattr(obj, name, value)


def _instance_result(
    part: Any,
    source: Any,
    link: Any,
    transform: _Transform,
    incoming: Optional[_JointPlacement],
) -> dict[str, Any]:
    part_id = _text(_field(part, "id"), "part instance.id")
    return {
        "part_instance_id": part_id,
        "part_number": _text(_field(part, "part_number"), f"part {part_id!r}.part_number"),
        "source_object": _object_name(source),
        "source_label": _object_label(source),
        "link_object": _object_name(link),
        "link_label": _object_label(link),
        "incoming_joint_id": _text(_field(incoming.joint, "id"), "joint.id") if incoming else None,
        "placement": transform.as_json(),
    }


def _joint_result(placement: _JointPlacement, units: str) -> dict[str, Any]:
    joint_id = _text(_field(placement.joint, "id"), "joint.id")
    kind = _text(_field(placement.joint, "kind"), f"joint {joint_id!r}.kind").lower()
    result: dict[str, Any] = {
        "id": joint_id,
        "kind": kind,
        "parent_part_id": placement.parent_part_id,
        "child_part_id": placement.child_part_id,
        "value": _clean_number(placement.value),
        "value_units": "radians" if kind == "revolute" else (units if kind == "prismatic" else None),
        "placement": placement.transform.as_json(),
    }
    if placement.axis is not None:
        result["axis_in_parent_interface_frame"] = [
            _clean_number(value) for value in placement.axis
        ]
    return result


def _json_bom(graph: Any) -> list[dict[str, Any]]:
    bom = getattr(graph, "bom", None)
    if not callable(bom):
        return []
    result: list[dict[str, Any]] = []
    for line in bom():
        to_dict = getattr(line, "to_dict", None)
        raw = to_dict() if callable(to_dict) else line
        # ``AssemblyGraph.bom`` is JSON-ready.  Copy through JSON to prevent a
        # non-serializable custom graph line from leaking into bridge output.
        result.append(json.loads(json.dumps(raw, allow_nan=False)))
    return result


def _cleanup_created(doc: Any, created: Sequence[str]) -> None:
    remover = getattr(doc, "removeObject", None)
    if not callable(remover):
        return
    for name in reversed(created):
        try:
            if doc.getObject(name) is not None:
                remover(name)
        except Exception:  # noqa: BLE001 - cleanup must not mask root failure.
            pass


def _placement_is_identity(placement: Any) -> bool:
    base = getattr(placement, "Base", None)
    try:
        translation = _vector(base, "source Placement.Base")
    except AssemblyCompilationError:
        return False
    if any(abs(component) > _EPSILON for component in translation):
        return False
    rotation = getattr(placement, "Rotation", None)
    if rotation is None:
        return False
    quaternion = getattr(rotation, "Q", None)
    if quaternion is not None:
        try:
            values = _vector4(quaternion, "source Placement.Rotation.Q")
        except AssemblyCompilationError:
            return False
        # Quaternion component ordering differs across wrappers, but identity
        # always has exactly one unit-magnitude component and three zeroes.
        return sum(1 for value in values if abs(abs(value) - 1.0) <= _EPSILON) == 1 and all(
            abs(value) <= _EPSILON or abs(abs(value) - 1.0) <= _EPSILON
            for value in values
        )
    angle = getattr(rotation, "Angle", None)
    try:
        numeric_angle = _number(angle, "source Placement.Rotation.Angle", [])
    except AssemblyCompilationError:
        return False
    return abs(math.sin(numeric_angle / 2.0)) <= _EPSILON


def _matrix_multiply(
    left: tuple[tuple[float, float, float], ...],
    right: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3))
        for row in range(3)
    )


def _matrix_vector(
    matrix: tuple[tuple[float, float, float], ...], vector: tuple[float, float, float]
) -> tuple[float, float, float]:
    return tuple(sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3))  # type: ignore[return-value]


def _transpose(
    matrix: tuple[tuple[float, float, float], ...]
) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(matrix[column][row] for column in range(3)) for row in range(3))


def _axis_angle_matrix(
    axis: tuple[float, float, float], angle: float
) -> tuple[tuple[float, float, float], ...]:
    x, y, z = axis
    cosine = math.cos(angle)
    sine = math.sin(angle)
    one_minus = 1.0 - cosine
    return (
        (cosine + x * x * one_minus, x * y * one_minus - z * sine, x * z * one_minus + y * sine),
        (y * x * one_minus + z * sine, cosine + y * y * one_minus, y * z * one_minus - x * sine),
        (z * x * one_minus - y * sine, z * y * one_minus + x * sine, cosine + z * z * one_minus),
    )


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise AssemblyCompilationError(f"{label} must be a finite three-number vector")
    return tuple(_finite(value, f"{label}[{index}]") for index, value in enumerate(value))  # type: ignore[return-value]


def _vector4(value: Any, label: str) -> tuple[float, float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 4:
        raise AssemblyCompilationError(f"{label} must be a finite four-number quaternion")
    return tuple(_finite(item, f"{label}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _normalise(vector: tuple[float, float, float], label: str) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= _EPSILON:
        raise AssemblyCompilationError(f"{label} must be non-zero")
    return tuple(component / magnitude for component in vector)  # type: ignore[return-value]


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _cross(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _number(value: Any, label: str, errors: list[str]) -> float:
    try:
        return _finite(value, label)
    except AssemblyCompilationError as exc:
        errors.append(str(exc))
        return 0.0


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise AssemblyCompilationError(f"{label} must be a finite number")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise AssemblyCompilationError(f"{label} must be a finite number") from exc
    if not math.isfinite(numeric):
        raise AssemblyCompilationError(f"{label} must be a finite number")
    return numeric


def _text(value: Any, label: str, errors: Optional[list[str]] = None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    message = f"{label} must be a non-empty string"
    if errors is not None:
        errors.append(message)
        return ""
    raise AssemblyCompilationError(message)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _object_name(obj: Any) -> str:
    value = getattr(obj, "Name", None)
    return value if isinstance(value, str) and value else "<unnamed>"


def _object_label(obj: Any) -> str:
    value = getattr(obj, "Label", None)
    return value if isinstance(value, str) and value else _object_name(obj)


def _object_type_id(obj: Any) -> str:
    value = getattr(obj, "TypeId", None)
    return value if isinstance(value, str) else ""


def _require_object(value: Any, message: str) -> None:
    if value is None:
        raise AssemblyCompilationError(message)


def _instance_label(part: Any) -> str:
    name = _string_or_empty(_field(part, "name", ""))
    number = _text(_field(part, "part_number"), "part instance.part_number")
    return f"{name or _text(_field(part, 'id'), 'part instance.id')} ({number})"


def _string_or_empty(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _freecad_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "OrionAssembly"
    if not sanitized[0].isalpha():
        sanitized = "Orion_" + sanitized
    return sanitized[:80]


def _clean_number(value: float) -> float:
    return 0.0 if abs(value) <= _EPSILON else float(value)


# ``with_translation`` is kept outside the dataclass body to make the identity
# construction above read naturally while preserving a tiny immutable type.
def _with_translation(self: _Transform, translation: tuple[float, float, float]) -> _Transform:
    return _Transform(rotation=self.rotation, translation=translation)


_Transform.with_translation = _with_translation  # type: ignore[attr-defined]


__all__ = [
    "AssemblyCompilationError",
    "AssemblyCompilerError",
    "COMPILER_VERSION",
    "PLACEMENT_FORMULA",
    "compile_assembly_graph",
]
