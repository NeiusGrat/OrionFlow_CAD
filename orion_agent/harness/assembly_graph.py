"""AssemblyGraph: a small, deterministic assembly IR for OrionFlow.

``FeatureGraph`` describes how to create one parametric part.  This module is
its deliberately separate companion: ``AssemblyGraph`` describes *which part
instances exist*, the interfaces exposed by those instances, and the joints
that connect them.  It does not solve mates or generate CAD geometry yet.  The
small, stdlib-only contract makes it safe to use both in the harness and in
offline validation tools before a CAD adapter is involved.

The JSON-like authoring form is intentionally compact::

    {
      "id": "linear_axis",
      "parts": [{"id": "base", "part_number": "OF-BASE-001"}],
      "interfaces": [{"id": "base.top", "part_id": "base", "kind": "planar"}],
      "joints": []
    }

An interface's optional frame uses the graph's declared units (``mm`` by
default).  A revolute or prismatic joint must declare a non-zero local axis;
limits, when supplied, use radians for a revolute joint and graph units for a
prismatic joint.  A part may reference a FeatureGraph or a purchased component
through its opaque ``definition`` mapping.  The assembly layer preserves that
reference without trying to compile the individual part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Iterable, Mapping, Optional, Sequence


SCHEMA_VERSION = "orion_assembly_v1"
SUPPORTED_JOINT_TYPES = frozenset({"fixed", "revolute", "prismatic"})
SUPPORTED_MATE_TYPES = frozenset({
    "fixed", "concentric", "coincident", "planar", "revolute", "prismatic", "belt",
})

# Degrees of freedom each mate removes between two rigid bodies (of six).
# ``belt`` is a coupling equation between two existing movable joints, not a
# body-to-body contact constraint, so it contributes one constraint equation.
MATE_DOF_REMOVED = {
    "fixed": 6,
    "revolute": 5,
    "prismatic": 5,
    "concentric": 4,   # shared axis: two translations + two rotations
    "coincident": 3,   # shared point/origin: three translations
    "planar": 3,       # face-on-face: one translation + two rotations
    "belt": 1,         # value_b = ratio * value_a
}


class AssemblyGraphError(ValueError):
    """Base class for malformed AssemblyGraph authoring data."""


class AssemblyGraphValidationError(AssemblyGraphError):
    """Raised when strict parsing encounters one or more graph errors."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("AssemblyGraph validation failed:\n- " + "\n- ".join(errors))


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssemblyGraphError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise AssemblyGraphError(f"{name} must be an array")
    return value


def _text(value: Any, name: str, *, default: Optional[str] = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise AssemblyGraphError(f"{name} must be a non-empty string")
    return value.strip()


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise AssemblyGraphError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AssemblyGraphError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise AssemblyGraphError(f"{name} must be a finite number")
    return number


def _vector(value: Any, name: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise AssemblyGraphError(f"{name} must be a three-number vector")
    return tuple(_finite_number(component, f"{name}[{index}]") for index, component in enumerate(value))  # type: ignore[return-value]


def _nonzero(vector: tuple[float, float, float]) -> bool:
    return any(abs(component) > 1e-12 for component in vector)


def _plain_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(_mapping(value, name))


@dataclass(frozen=True)
class Frame:
    """Optional coordinate frame attached to an interface.

    ``origin`` is measured in the assembly's units.  Axis vectors are unitless
    directions and need not be normalized; validation only requires a usable,
    non-degenerate frame when axes are supplied.
    """

    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    x_axis: Optional[tuple[float, float, float]] = None
    z_axis: Optional[tuple[float, float, float]] = None

    @classmethod
    def from_dict(cls, data: Any) -> "Frame":
        if data is None:
            return cls()
        raw = _mapping(data, "frame")
        # ``origin_mm`` is accepted for a convenient hand-authored v0.1 alias;
        # emitted data always uses the unit-neutral ``origin`` field.
        origin = _vector(raw.get("origin", raw.get("origin_mm", (0, 0, 0))), "frame.origin")
        x_axis = _vector(raw["x_axis"], "frame.x_axis") if "x_axis" in raw else None
        z_axis = _vector(raw["z_axis"], "frame.z_axis") if "z_axis" in raw else None
        return cls(origin=origin, x_axis=x_axis, z_axis=z_axis)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"origin": list(self.origin)}
        if self.x_axis is not None:
            result["x_axis"] = list(self.x_axis)
        if self.z_axis is not None:
            result["z_axis"] = list(self.z_axis)
        return result

    def validate(self, label: str) -> list[str]:
        errors: list[str] = []
        if self.x_axis is not None and not _nonzero(self.x_axis):
            errors.append(f"{label}: x_axis must be non-zero")
        if self.z_axis is not None and not _nonzero(self.z_axis):
            errors.append(f"{label}: z_axis must be non-zero")
        if self.x_axis is not None and self.z_axis is not None:
            cross = (
                self.x_axis[1] * self.z_axis[2] - self.x_axis[2] * self.z_axis[1],
                self.x_axis[2] * self.z_axis[0] - self.x_axis[0] * self.z_axis[2],
                self.x_axis[0] * self.z_axis[1] - self.x_axis[1] * self.z_axis[0],
            )
            if not _nonzero(cross):
                errors.append(f"{label}: x_axis and z_axis must not be parallel")
        return errors


@dataclass(frozen=True)
class PartInstance:
    """A single physical occurrence of a custom or purchased component."""

    id: str
    part_number: str
    name: str = ""
    revision: str = ""
    manufacturer: str = ""
    definition: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "PartInstance":
        raw = _mapping(data, f"parts[{index}]")
        definition: dict[str, Any]
        if "definition" in raw:
            definition = _plain_mapping(raw["definition"], f"parts[{index}].definition")
        elif "model" in raw:
            definition = _plain_mapping(raw["model"], f"parts[{index}].model")
        elif "feature_graph" in raw:
            definition = {"kind": "feature_graph", "id": raw["feature_graph"]}
        else:
            definition = {}
        return cls(
            id=_text(raw.get("id"), f"parts[{index}].id"),
            part_number=_text(raw.get("part_number"), f"parts[{index}].part_number"),
            name=_text(raw.get("name"), f"parts[{index}].name", default=""),
            revision=_text(raw.get("revision"), f"parts[{index}].revision", default=""),
            manufacturer=_text(raw.get("manufacturer"), f"parts[{index}].manufacturer", default=""),
            definition=definition,
            metadata=_plain_mapping(raw.get("metadata"), f"parts[{index}].metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "part_number": self.part_number}
        if self.name:
            result["name"] = self.name
        if self.revision:
            result["revision"] = self.revision
        if self.manufacturer:
            result["manufacturer"] = self.manufacturer
        if self.definition:
            result["definition"] = dict(self.definition)
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class Interface:
    """A named mating contract exposed by one part instance."""

    id: str
    part_id: str
    kind: str
    frame: Frame = field(default_factory=Frame)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def part_instance(self) -> str:
        """Alias that makes the instance ownership explicit to callers."""
        return self.part_id

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "Interface":
        raw = _mapping(data, f"interfaces[{index}]")
        # ``part_instance`` is a readable authoring alias.  The canonical form
        # uses ``part_id`` because it is the graph key.
        part_id = raw.get("part_id", raw.get("part_instance"))
        return cls(
            id=_text(raw.get("id"), f"interfaces[{index}].id"),
            part_id=_text(part_id, f"interfaces[{index}].part_id"),
            kind=_text(raw.get("kind", raw.get("type")), f"interfaces[{index}].kind"),
            frame=Frame.from_dict(raw.get("frame")),
            metadata=_plain_mapping(raw.get("metadata"), f"interfaces[{index}].metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "part_id": self.part_id,
            "kind": self.kind,
            "frame": self.frame.to_dict(),
        }
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class JointLimits:
    """Optional positional, velocity, and effort limits for one joint."""

    lower: Optional[float] = None
    upper: Optional[float] = None
    velocity: Optional[float] = None
    effort: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any, label: str) -> "JointLimits":
        raw = _mapping(data, label)

        def optional_number(key: str) -> Optional[float]:
            return _finite_number(raw[key], f"{label}.{key}") if key in raw else None

        return cls(
            lower=optional_number("lower"),
            upper=optional_number("upper"),
            velocity=optional_number("velocity"),
            effort=optional_number("effort"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("lower", self.lower),
                ("upper", self.upper),
                ("velocity", self.velocity),
                ("effort", self.effort),
            )
            if value is not None
        }

    def validate(self, label: str) -> list[str]:
        errors: list[str] = []
        if (self.lower is None) != (self.upper is None):
            errors.append(f"{label}: lower and upper must be supplied together")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            errors.append(f"{label}: lower must be less than or equal to upper")
        if self.velocity is not None and self.velocity < 0:
            errors.append(f"{label}: velocity must be non-negative")
        if self.effort is not None and self.effort < 0:
            errors.append(f"{label}: effort must be non-negative")
        return errors


@dataclass(frozen=True)
class Joint:
    """A directed parent-to-child fixed or single-degree-of-freedom joint."""

    id: str
    kind: str
    parent_interface: str
    child_interface: str
    axis: Optional[tuple[float, float, float]] = None
    limits: Optional[JointLimits] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def joint_type(self) -> str:
        """Explicit alias for consumers that use ``joint_type`` nomenclature."""
        return self.kind

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "Joint":
        raw = _mapping(data, f"joints[{index}]")
        kind = _text(raw.get("kind", raw.get("type")), f"joints[{index}].kind").lower()
        axis = _vector(raw["axis"], f"joints[{index}].axis") if "axis" in raw else None
        limits_value = raw.get("limits", raw.get("limit"))
        return cls(
            id=_text(raw.get("id"), f"joints[{index}].id"),
            kind=kind,
            parent_interface=_text(raw.get("parent_interface"), f"joints[{index}].parent_interface"),
            child_interface=_text(raw.get("child_interface"), f"joints[{index}].child_interface"),
            axis=axis,
            limits=(JointLimits.from_dict(limits_value, f"joints[{index}].limits")
                    if limits_value is not None else None),
            metadata=_plain_mapping(raw.get("metadata"), f"joints[{index}].metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "parent_interface": self.parent_interface,
            "child_interface": self.child_interface,
        }
        if self.axis is not None:
            result["axis"] = list(self.axis)
        if self.limits is not None:
            result["limits"] = self.limits.to_dict()
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class Mate:
    """A declarative mating constraint between two interfaces.

    Mates are the constraint view of the assembly; joints are its rooted
    kinematic-tree view.  The two coexist: a CAD mate solver consumes mates,
    while URDF export and the link compiler consume joints.  A ``belt`` mate
    is special — it couples two already-declared movable joints through a
    finite non-zero ``ratio`` (``value_b = ratio * value_a``; for a
    belt-driven linear axis the ratio is the pulley pitch radius, giving
    mm of travel per radian).
    """

    id: str
    kind: str
    interface_a: str
    interface_b: str
    ratio: Optional[float] = None
    couples: Optional[tuple[str, str]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "Mate":
        raw = _mapping(data, f"mates[{index}]")
        kind = _text(raw.get("kind", raw.get("type")), f"mates[{index}].kind").lower()
        couples_raw = raw.get("couples", raw.get("coupled_joints"))
        couples: Optional[tuple[str, str]] = None
        if couples_raw is not None:
            items = _list(couples_raw, f"mates[{index}].couples")
            if len(items) != 2:
                raise AssemblyGraphError(f"mates[{index}].couples must name exactly two joints")
            couples = (
                _text(items[0], f"mates[{index}].couples[0]"),
                _text(items[1], f"mates[{index}].couples[1]"),
            )
        return cls(
            id=_text(raw.get("id"), f"mates[{index}].id"),
            kind=kind,
            interface_a=_text(raw.get("interface_a"), f"mates[{index}].interface_a"),
            interface_b=_text(raw.get("interface_b"), f"mates[{index}].interface_b"),
            ratio=(_finite_number(raw["ratio"], f"mates[{index}].ratio")
                   if "ratio" in raw else None),
            couples=couples,
            metadata=_plain_mapping(raw.get("metadata"), f"mates[{index}].metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "interface_a": self.interface_a,
            "interface_b": self.interface_b,
        }
        if self.ratio is not None:
            result["ratio"] = self.ratio
        if self.couples is not None:
            result["couples"] = list(self.couples)
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    @property
    def equivalent_joint_kind(self) -> Optional[str]:
        """The tree-joint kind this mate lowers to, if it fully lowers.

        Partial constraints (concentric, coincident, planar) and couplings
        (belt) have no single-joint equivalent and need a mate solver.
        """
        return self.kind if self.kind in SUPPORTED_JOINT_TYPES else None


@dataclass(frozen=True)
class BOMLine:
    """A deterministic aggregate of matching physical part instances."""

    part_number: str
    quantity: int
    instance_ids: tuple[str, ...]
    name: str = ""
    revision: str = ""
    manufacturer: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "part_number": self.part_number,
            "quantity": self.quantity,
            "instance_ids": list(self.instance_ids),
        }
        if self.name:
            result["name"] = self.name
        if self.revision:
            result["revision"] = self.revision
        if self.manufacturer:
            result["manufacturer"] = self.manufacturer
        return result


@dataclass(frozen=True)
class AssemblyGraph:
    """The v0.1 assembly-level IR used alongside per-part FeatureGraphs."""

    id: str
    name: str = ""
    schema_version: str = SCHEMA_VERSION
    units: str = "mm"
    parts: tuple[PartInstance, ...] = ()
    interfaces: tuple[Interface, ...] = ()
    joints: tuple[Joint, ...] = ()
    mates: tuple[Mate, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, *, validate: bool = False) -> "AssemblyGraph":
        """Parse a JSON-like object into dataclasses.

        Parsing rejects invalid primitive shapes immediately.  Cross-reference
        and kinematic checks remain available through :meth:`validate`; pass
        ``validate=True`` to turn those results into an exception at the input
        boundary.
        """
        raw = _mapping(data, "assembly graph")
        graph = cls(
            id=_text(raw.get("id"), "id"),
            name=_text(raw.get("name"), "name", default=""),
            schema_version=_text(raw.get("schema_version"), "schema_version", default=SCHEMA_VERSION),
            units=_text(raw.get("units"), "units", default="mm"),
            parts=tuple(PartInstance.from_dict(item, index) for index, item in enumerate(_list(raw.get("parts", []), "parts"))),
            interfaces=tuple(Interface.from_dict(item, index) for index, item in enumerate(_list(raw.get("interfaces", []), "interfaces"))),
            joints=tuple(Joint.from_dict(item, index) for index, item in enumerate(_list(raw.get("joints", []), "joints"))),
            mates=tuple(Mate.from_dict(item, index) for index, item in enumerate(_list(raw.get("mates", []), "mates"))),
            metadata=_plain_mapping(raw.get("metadata"), "metadata"),
        )
        if validate:
            graph.assert_valid()
        return graph

    def to_dict(self) -> dict[str, Any]:
        """Return canonical JSON-ready data using only plain built-in types."""
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "units": self.units,
            "parts": [part.to_dict() for part in self.parts],
            "interfaces": [interface.to_dict() for interface in self.interfaces],
            "joints": [joint.to_dict() for joint in self.joints],
        }
        if self.mates:
            result["mates"] = [mate.to_dict() for mate in self.mates]
        if self.name:
            result["name"] = self.name
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    def validate(self) -> list[str]:
        """Return deterministic, actionable structural and kinematic errors."""
        errors: list[str] = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append(
                f"unsupported schema_version {self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )
        if not self.parts:
            errors.append("assembly has no part instances")

        part_ids = [part.id for part in self.parts]
        interface_ids = [interface.id for interface in self.interfaces]
        joint_ids = [joint.id for joint in self.joints]
        mate_ids = [mate.id for mate in self.mates]
        errors.extend(_duplicate_errors(part_ids, "part instance"))
        errors.extend(_duplicate_errors(interface_ids, "interface"))
        errors.extend(_duplicate_errors(joint_ids, "joint"))
        errors.extend(_duplicate_errors(mate_ids, "mate"))

        known_parts = set(part_ids)
        interfaces = {interface.id: interface for interface in self.interfaces}
        for interface in self.interfaces:
            if interface.part_id not in known_parts:
                errors.append(
                    f"interface {interface.id!r} references unknown part instance {interface.part_id!r}"
                )
            errors.extend(interface.frame.validate(f"interface {interface.id!r} frame"))

        seen_pairs: set[frozenset[str]] = set()
        adjacency: dict[str, set[str]] = {part_id: set() for part_id in known_parts}
        for joint in self.joints:
            label = f"joint {joint.id!r}"
            if joint.kind not in SUPPORTED_JOINT_TYPES:
                errors.append(
                    f"{label} has unsupported kind {joint.kind!r}; supported: "
                    + ", ".join(sorted(SUPPORTED_JOINT_TYPES))
                )
            parent = interfaces.get(joint.parent_interface)
            child = interfaces.get(joint.child_interface)
            if parent is None:
                errors.append(f"{label} references unknown parent interface {joint.parent_interface!r}")
            if child is None:
                errors.append(f"{label} references unknown child interface {joint.child_interface!r}")
            if parent is None or child is None:
                continue
            if parent.id == child.id:
                errors.append(f"{label} must use two distinct interfaces")
                continue
            if parent.part_id == child.part_id:
                errors.append(f"{label} connects interfaces on the same part instance {parent.part_id!r}")
                continue

            pair = frozenset((parent.id, child.id))
            if pair in seen_pairs:
                errors.append(f"{label} duplicates an existing interface pair")
            seen_pairs.add(pair)
            adjacency.setdefault(parent.part_id, set()).add(child.part_id)
            adjacency.setdefault(child.part_id, set()).add(parent.part_id)

            if joint.kind in {"revolute", "prismatic"}:
                if joint.axis is None:
                    errors.append(f"{label} ({joint.kind}) requires a non-zero axis")
                elif not _nonzero(joint.axis):
                    errors.append(f"{label} ({joint.kind}) axis must be non-zero")
            if joint.limits is not None:
                errors.extend(joint.limits.validate(f"{label} limits"))

        joints_by_id = {joint.id: joint for joint in self.joints}
        for mate in self.mates:
            label = f"mate {mate.id!r}"
            if mate.kind not in SUPPORTED_MATE_TYPES:
                errors.append(
                    f"{label} has unsupported kind {mate.kind!r}; supported: "
                    + ", ".join(sorted(SUPPORTED_MATE_TYPES))
                )
            side_a = interfaces.get(mate.interface_a)
            side_b = interfaces.get(mate.interface_b)
            if side_a is None:
                errors.append(f"{label} references unknown interface {mate.interface_a!r}")
            if side_b is None:
                errors.append(f"{label} references unknown interface {mate.interface_b!r}")
            if side_a is None or side_b is None:
                continue
            if side_a.id == side_b.id:
                errors.append(f"{label} must use two distinct interfaces")
                continue
            if side_a.part_id == side_b.part_id:
                errors.append(
                    f"{label} mates interfaces on the same part instance {side_a.part_id!r}"
                )
                continue
            adjacency.setdefault(side_a.part_id, set()).add(side_b.part_id)
            adjacency.setdefault(side_b.part_id, set()).add(side_a.part_id)

            if mate.kind == "belt":
                if mate.ratio is None or abs(mate.ratio) <= 1e-12:
                    errors.append(f"{label} (belt) requires a finite non-zero ratio")
                if mate.couples is None:
                    errors.append(
                        f"{label} (belt) requires 'couples' naming the two joints it links"
                    )
                else:
                    for joint_id in mate.couples:
                        coupled = joints_by_id.get(joint_id)
                        if coupled is None:
                            errors.append(f"{label} (belt) couples unknown joint {joint_id!r}")
                        elif coupled.kind not in {"revolute", "prismatic"}:
                            errors.append(
                                f"{label} (belt) can only couple revolute or prismatic "
                                f"joints; joint {joint_id!r} is {coupled.kind!r}"
                            )
                    if mate.couples[0] == mate.couples[1]:
                        errors.append(f"{label} (belt) must couple two distinct joints")
            else:
                if mate.ratio is not None:
                    errors.append(f"{label} ({mate.kind}) does not accept a ratio")
                if mate.couples is not None:
                    errors.append(f"{label} ({mate.kind}) does not accept coupled joints")

        if len(known_parts) > 1:
            components = _connected_components(known_parts, adjacency)
            if len(components) > 1:
                rendered = "; ".join(", ".join(sorted(component)) for component in components)
                errors.append(f"assembly graph is disconnected: {rendered}")
        return errors

    def assert_valid(self) -> None:
        """Raise :class:`AssemblyGraphValidationError` if validation fails."""
        errors = self.validate()
        if errors:
            raise AssemblyGraphValidationError(errors)

    def interface(self, interface_id: str) -> Optional[Interface]:
        """Look up one named interface without exposing internal dictionaries."""
        return next((item for item in self.interfaces if item.id == interface_id), None)

    def part(self, part_id: str) -> Optional[PartInstance]:
        """Look up one physical part instance."""
        return next((item for item in self.parts if item.id == part_id), None)

    def connected_components(self) -> tuple[tuple[str, ...], ...]:
        """Return weakly connected part-instance groups in deterministic order.

        Both joints and mates connect part instances: an assembly held purely
        by mates is connected even before its kinematic tree is authored.
        """
        part_ids = {part.id for part in self.parts}
        interfaces = {interface.id: interface for interface in self.interfaces}
        adjacency: dict[str, set[str]] = {part_id: set() for part_id in part_ids}

        def connect(id_a: Optional[Interface], id_b: Optional[Interface]) -> None:
            if id_a is not None and id_b is not None and id_a.part_id != id_b.part_id:
                if id_a.part_id in adjacency and id_b.part_id in adjacency:
                    adjacency[id_a.part_id].add(id_b.part_id)
                    adjacency[id_b.part_id].add(id_a.part_id)

        for joint in self.joints:
            connect(interfaces.get(joint.parent_interface), interfaces.get(joint.child_interface))
        for mate in self.mates:
            connect(interfaces.get(mate.interface_a), interfaces.get(mate.interface_b))
        return tuple(tuple(sorted(component)) for component in _connected_components(part_ids, adjacency))

    def mobility_estimate(self) -> dict[str, Any]:
        """Return a Gruebler/Kutzbach screening estimate of assembly mobility.

        ``dof = 6 * (bodies - 1) - sum(constraints)`` over mates (plus tree
        joints that have no corresponding mate).  This is a screening number
        only: redundant constraints, parallel mechanisms, and geometric
        special cases make the true mobility differ, so callers must treat a
        surprising value as a review trigger, not a proof.
        """
        interfaces = {interface.id: interface for interface in self.interfaces}
        mated_pairs: set[frozenset[str]] = set()
        removed = 0
        for mate in self.mates:
            removed += MATE_DOF_REMOVED.get(mate.kind, 0)
            side_a = interfaces.get(mate.interface_a)
            side_b = interfaces.get(mate.interface_b)
            if side_a is not None and side_b is not None:
                mated_pairs.add(frozenset((side_a.part_id, side_b.part_id)))
        # A joint on a pair that has no mate contributes its own constraint,
        # so a joints-only graph still gets a meaningful estimate.
        joint_removed = {"fixed": 6, "revolute": 5, "prismatic": 5}
        for joint in self.joints:
            parent = interfaces.get(joint.parent_interface)
            child = interfaces.get(joint.child_interface)
            if parent is None or child is None:
                continue
            if frozenset((parent.part_id, child.part_id)) in mated_pairs:
                continue
            removed += joint_removed.get(joint.kind, 0)
        bodies = len(self.parts)
        dof = 6 * max(bodies - 1, 0) - removed
        return {
            "bodies": bodies,
            "constraints_removed_dof": removed,
            "estimated_dof": dof,
            "method": "gruebler_screening",
            "limitations": [
                "Screening estimate only; redundant or special-geometry constraints "
                "change true mobility and require a mate-solver or engineering review.",
            ],
        }

    def has_kinematic_cycle(self) -> bool:
        """Report whether the undirected part graph contains a closed loop.

        Closed loops are not automatically invalid: parallel mechanisms and
        structural assemblies legitimately contain them.  Callers can decide
        whether their downstream mate solver supports such a topology.
        """
        nodes = {part.id for part in self.parts}
        interfaces = {interface.id: interface for interface in self.interfaces}
        edges: set[frozenset[str]] = set()
        for joint in self.joints:
            parent = interfaces.get(joint.parent_interface)
            child = interfaces.get(joint.child_interface)
            if parent is not None and child is not None and parent.part_id != child.part_id:
                edges.add(frozenset((parent.part_id, child.part_id)))
        component_count = len(self.connected_components())
        return len(edges) > len(nodes) - component_count

    def bom(self) -> tuple[BOMLine, ...]:
        """Aggregate physical occurrences by manufacturer part identity."""
        grouped: dict[tuple[str, str, str], list[PartInstance]] = {}
        for part in self.parts:
            key = (part.part_number, part.revision, part.manufacturer)
            grouped.setdefault(key, []).append(part)
        lines: list[BOMLine] = []
        for key in sorted(grouped):
            entries = grouped[key]
            exemplar = entries[0]
            lines.append(
                BOMLine(
                    part_number=exemplar.part_number,
                    quantity=len(entries),
                    instance_ids=tuple(part.id for part in entries),
                    name=exemplar.name,
                    revision=exemplar.revision,
                    manufacturer=exemplar.manufacturer,
                )
            )
        return tuple(lines)


def _duplicate_errors(values: Iterable[str], noun: str) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [f"duplicate {noun} id {value!r}" for value in sorted(counts) if counts[value] > 1]


def _connected_components(
    nodes: Iterable[str], adjacency: Mapping[str, set[str]]
) -> tuple[set[str], ...]:
    remaining = set(nodes)
    components: list[set[str]] = []
    while remaining:
        root = min(remaining)
        stack = [root]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            stack.extend(sorted(adjacency.get(current, set()) - component, reverse=True))
        components.append(component)
    return tuple(components)


def parse_assembly_graph(data: Any, *, strict: bool = True) -> AssemblyGraph:
    """Parse authoring data, optionally rejecting graph-level errors.

    ``strict=True`` is the safe boundary for an LLM or API request.  Set it to
    ``False`` to inspect an in-progress graph and call :func:`validate` for its
    actionable error list.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise AssemblyGraphError("assembly graph must be a JSON object") from exc
    return AssemblyGraph.from_dict(data, validate=strict)


def parse(data: Any, *, strict: bool = True) -> AssemblyGraph:
    """Short alias for :func:`parse_assembly_graph`."""
    return parse_assembly_graph(data, strict=strict)


def validate(data: Any) -> list[str]:
    """Validate JSON-like data or an :class:`AssemblyGraph` without raising."""
    if isinstance(data, AssemblyGraph):
        return data.validate()
    try:
        return AssemblyGraph.from_dict(data, validate=False).validate()
    except AssemblyGraphError as exc:
        return [str(exc)]


def aggregate_bom(data: Any) -> list[dict[str, Any]]:
    """Return JSON-ready, deterministic BOM lines for an assembly graph."""
    graph = data if isinstance(data, AssemblyGraph) else parse_assembly_graph(data)
    return [line.to_dict() for line in graph.bom()]


def summarize(data: Any) -> str:
    """Return a compact, deterministic description for an agent observation."""
    graph = data if isinstance(data, AssemblyGraph) else parse_assembly_graph(data)
    kinds: dict[str, int] = {kind: 0 for kind in sorted(SUPPORTED_JOINT_TYPES)}
    for joint in graph.joints:
        kinds[joint.kind] = kinds.get(joint.kind, 0) + 1
    degrees_of_freedom = kinds.get("revolute", 0) + kinds.get("prismatic", 0)
    lines = [
        f"AssemblyGraph '{graph.id}': {len(graph.parts)} part instance(s), "
        f"{len(graph.interfaces)} interface(s), {len(graph.joints)} joint(s), "
        f"{len(graph.mates)} mate(s), "
        f"{degrees_of_freedom} modeled degree(s) of freedom.",
        "Joint types: " + ", ".join(
            f"{kind}={kinds.get(kind, 0)}" for kind in sorted(SUPPORTED_JOINT_TYPES)
        ),
        f"BOM: {len(graph.bom())} unique line item(s).",
    ]
    if graph.mates:
        mate_kinds: dict[str, int] = {}
        for mate in graph.mates:
            mate_kinds[mate.kind] = mate_kinds.get(mate.kind, 0) + 1
        lines.insert(2, "Mate types: " + ", ".join(
            f"{kind}={count}" for kind, count in sorted(mate_kinds.items())
        ))
    if graph.has_kinematic_cycle():
        lines.append(
            "Topology: closed kinematic loop detected; downstream URDF or mate "
            "solvers need an explicit loop/mimic strategy."
        )
    return "\n".join(lines)


def normalize(data: Any) -> dict[str, Any]:
    """Parse and emit the canonical assembly authoring form without validation."""
    return parse_assembly_graph(data, strict=False).to_dict()


__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_JOINT_TYPES",
    "SUPPORTED_MATE_TYPES",
    "MATE_DOF_REMOVED",
    "AssemblyGraphError",
    "AssemblyGraphValidationError",
    "Frame",
    "PartInstance",
    "Interface",
    "JointLimits",
    "Joint",
    "Mate",
    "BOMLine",
    "AssemblyGraph",
    "parse_assembly_graph",
    "parse",
    "validate",
    "aggregate_bom",
    "summarize",
    "normalize",
]
