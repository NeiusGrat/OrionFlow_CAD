"""Typed design-intent layer above :mod:`assembly_graph`.

``AssemblyGraph`` answers *how part instances connect*.  This module answers
the questions around it that a real robotics release needs:

- :class:`ComponentVariant` — one exact, orderable manufacturer part
  (part number + drawing revision), distinct from the family-level candidate
  records in the knowledge package.
- :class:`InterfaceContract` — the mating contract a variant or custom part
  must satisfy before CAD dimensioning, loadable from the packaged robotics
  interface records.
- :class:`RobotLink` — the physical view of one part instance: mass, centre
  of gravity, inertia, meshes, and a screening envelope, each carrying an
  explicit basis so an estimated number can never masquerade as verified.
- :class:`KinematicJoint` — the kinematic view of a joint (alias of
  :class:`~orion_agent.harness.assembly_graph.Joint`, whose ``joint_type``
  and limit semantics are already kinematic).
- :class:`AssemblySpec` — the bundle: requirements, variants, contracts,
  the AssemblyGraph, links, and externally attached evidence.

Everything is stdlib-only and deterministic, like the rest of the harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Optional, Sequence

from orion_agent.harness.assembly_graph import (
    AssemblyGraph,
    AssemblyGraphError,
    Joint,
    parse_assembly_graph,
)

SPEC_SCHEMA_VERSION = "orion_assembly_spec_v1"

# The kinematic view of a joint: parent/child interfaces, axis, and limits.
# Kept as a first-class name so spec-level code reads kinematically.
KinematicJoint = Joint

# A value's provenance. "unknown" is the honest default; validation treats
# anything but source_specific/measured as evidence still to be produced.
VALUE_BASES = ("source_specific", "measured", "estimated", "unknown")


class AssemblySpecError(ValueError):
    """Raised for malformed AssemblySpec authoring data."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssemblySpecError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> Sequence[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AssemblySpecError(f"{name} must be an array")
    return value


def _text(value: Any, name: str, *, default: Optional[str] = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise AssemblySpecError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_number(value: Any, name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AssemblySpecError(f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AssemblySpecError(f"{name} must be a number") from exc


def _optional_vector(value: Any, name: str) -> Optional[tuple[float, float, float]]:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise AssemblySpecError(f"{name} must be a three-number vector")
    return tuple(float(component) for component in value)  # type: ignore[return-value]


def _basis(value: Any, name: str) -> str:
    basis = _text(value, name, default="unknown").lower()
    if basis not in VALUE_BASES:
        raise AssemblySpecError(
            f"{name} must be one of: {', '.join(VALUE_BASES)}"
        )
    return basis


@dataclass(frozen=True)
class DrawingReference:
    """A controlled-drawing pointer for an exact purchased component.

    ``revision`` empty means the current revision has not been recorded —
    release readiness gates on it.  This type never invents a revision.
    """

    document: str = ""
    revision: str = ""
    retrieved: str = ""

    @classmethod
    def from_dict(cls, data: Any, name: str) -> "DrawingReference":
        if data is None:
            return cls()
        raw = _mapping(data, name)
        return cls(
            document=_text(raw.get("document"), f"{name}.document", default=""),
            revision=_text(raw.get("revision"), f"{name}.revision", default=""),
            retrieved=_text(raw.get("retrieved"), f"{name}.retrieved", default=""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("document", self.document),
                ("revision", self.revision),
                ("retrieved", self.retrieved),
            )
            if value
        }

    @property
    def is_revision_controlled(self) -> bool:
        return bool(self.document and self.revision)


@dataclass(frozen=True)
class ComponentVariant:
    """One exact, orderable component: manufacturer + part number + drawing.

    A variant is what a candidate family record resolves into.  It links back
    to the knowledge package via ``component_id`` so provenance rules keep
    applying, and it carries the drawing revision that a released BOM needs.
    """

    id: str
    manufacturer: str
    manufacturer_part_number: str
    component_id: str = ""
    description: str = ""
    drawing: DrawingReference = field(default_factory=DrawingReference)
    source_id: str = ""
    data_status: str = "candidate"
    engineering_review: str = "required"
    mass_kg: Optional[float] = None
    mass_basis: str = "unknown"
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, index: int = 0) -> "ComponentVariant":
        raw = _mapping(data, f"variants[{index}]")
        label = f"variants[{index}]"
        return cls(
            id=_text(raw.get("id"), f"{label}.id"),
            manufacturer=_text(raw.get("manufacturer"), f"{label}.manufacturer"),
            manufacturer_part_number=_text(
                raw.get("manufacturer_part_number", raw.get("mpn")),
                f"{label}.manufacturer_part_number",
            ),
            component_id=_text(raw.get("component_id"), f"{label}.component_id", default=""),
            description=_text(raw.get("description"), f"{label}.description", default=""),
            drawing=DrawingReference.from_dict(raw.get("drawing"), f"{label}.drawing"),
            source_id=_text(raw.get("source_id"), f"{label}.source_id", default=""),
            data_status=_text(raw.get("data_status"), f"{label}.data_status", default="candidate"),
            engineering_review=_text(
                raw.get("engineering_review"), f"{label}.engineering_review", default="required"
            ),
            mass_kg=_optional_number(raw.get("mass_kg"), f"{label}.mass_kg"),
            mass_basis=_basis(raw.get("mass_basis"), f"{label}.mass_basis"),
            parameters=dict(_mapping(raw.get("parameters", {}), f"{label}.parameters")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "manufacturer_part_number": self.manufacturer_part_number,
            "data_status": self.data_status,
            "engineering_review": self.engineering_review,
            "mass_basis": self.mass_basis,
        }
        if self.component_id:
            result["component_id"] = self.component_id
        if self.description:
            result["description"] = self.description
        drawing = self.drawing.to_dict()
        if drawing:
            result["drawing"] = drawing
        if self.source_id:
            result["source_id"] = self.source_id
        if self.mass_kg is not None:
            result["mass_kg"] = self.mass_kg
        if self.parameters:
            result["parameters"] = dict(self.parameters)
        return result

    def release_blockers(self) -> list[str]:
        """Deterministic reasons this variant cannot back a released BOM line."""
        blockers: list[str] = []
        if not self.drawing.is_revision_controlled:
            blockers.append(
                f"variant {self.id!r} ({self.manufacturer_part_number}) has no "
                "revision-controlled drawing recorded"
            )
        if self.engineering_review != "approved":
            blockers.append(
                f"variant {self.id!r} engineering review is "
                f"{self.engineering_review!r}, not 'approved'"
            )
        return blockers


@dataclass(frozen=True)
class InterfaceContract:
    """The mating contract a component or custom part must satisfy.

    Mirrors the packaged robotics interface records so a spec can pin the
    exact contracts it builds against; :meth:`from_knowledge_record` converts
    a retrieved record without losing its provenance fields.
    """

    id: str
    title: str = ""
    category: str = ""
    data_status: str = "candidate"
    engineering_review: str = "required"
    frame_convention: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any, index: int = 0) -> "InterfaceContract":
        raw = _mapping(data, f"contracts[{index}]")
        label = f"contracts[{index}]"
        contract = raw.get("contract")
        nested = _mapping(contract, f"{label}.contract") if contract is not None else {}

        def strings(source: Mapping[str, Any], key: str) -> tuple[str, ...]:
            return tuple(str(item) for item in _list(source.get(key), f"{label}.{key}"))

        return cls(
            id=_text(raw.get("id"), f"{label}.id"),
            title=_text(raw.get("title"), f"{label}.title", default=""),
            category=_text(raw.get("category"), f"{label}.category", default=""),
            data_status=_text(raw.get("data_status"), f"{label}.data_status", default="candidate"),
            engineering_review=_text(
                raw.get("engineering_review"), f"{label}.engineering_review", default="required"
            ),
            frame_convention=strings(nested or raw, "frame_convention"),
            required_inputs=strings(nested or raw, "required_inputs"),
            constraints=strings(nested or raw, "constraints"),
            verification=strings(nested or raw, "verification"),
            sources=strings(raw, "sources"),
        )

    # A packaged robotics interface record is already this shape.
    from_knowledge_record = from_dict

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "data_status": self.data_status,
            "engineering_review": self.engineering_review,
            "contract": {
                "frame_convention": list(self.frame_convention),
                "required_inputs": list(self.required_inputs),
                "constraints": list(self.constraints),
                "verification": list(self.verification),
            },
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class RobotLink:
    """Physical properties of one part instance, with explicit provenance.

    ``envelope`` is a local axis-aligned box ``{"size": [x, y, z],
    "origin": [x, y, z]}`` in graph units, usable for placeholder geometry
    and screening interference checks.  Mass/CoG/inertia values carry a
    basis; only ``source_specific`` or ``measured`` values count as verified
    downstream.
    """

    part_instance_id: str
    variant_id: str = ""
    mass_kg: Optional[float] = None
    mass_basis: str = "unknown"
    com: Optional[tuple[float, float, float]] = None
    com_basis: str = "unknown"
    inertia: Optional[tuple[float, float, float, float, float, float]] = None
    inertia_basis: str = "unknown"
    visual_mesh: str = ""
    collision_mesh: str = ""
    envelope: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, index: int = 0) -> "RobotLink":
        raw = _mapping(data, f"links[{index}]")
        label = f"links[{index}]"
        inertia_raw = raw.get("inertia")
        inertia: Optional[tuple[float, ...]] = None
        if inertia_raw is not None:
            items = _list(inertia_raw, f"{label}.inertia")
            if len(items) != 6:
                raise AssemblySpecError(
                    f"{label}.inertia must be [ixx, ixy, ixz, iyy, iyz, izz]"
                )
            inertia = tuple(float(item) for item in items)
        envelope = raw.get("envelope")
        return cls(
            part_instance_id=_text(
                raw.get("part_instance_id", raw.get("part_id")),
                f"{label}.part_instance_id",
            ),
            variant_id=_text(raw.get("variant_id"), f"{label}.variant_id", default=""),
            mass_kg=_optional_number(raw.get("mass_kg"), f"{label}.mass_kg"),
            mass_basis=_basis(raw.get("mass_basis"), f"{label}.mass_basis"),
            com=_optional_vector(raw.get("com"), f"{label}.com"),
            com_basis=_basis(raw.get("com_basis"), f"{label}.com_basis"),
            inertia=inertia,  # type: ignore[arg-type]
            inertia_basis=_basis(raw.get("inertia_basis"), f"{label}.inertia_basis"),
            visual_mesh=_text(raw.get("visual_mesh"), f"{label}.visual_mesh", default=""),
            collision_mesh=_text(raw.get("collision_mesh"), f"{label}.collision_mesh", default=""),
            envelope=dict(_mapping(envelope, f"{label}.envelope")) if envelope else {},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "part_instance_id": self.part_instance_id,
            "mass_basis": self.mass_basis,
            "com_basis": self.com_basis,
            "inertia_basis": self.inertia_basis,
        }
        if self.variant_id:
            result["variant_id"] = self.variant_id
        if self.mass_kg is not None:
            result["mass_kg"] = self.mass_kg
        if self.com is not None:
            result["com"] = list(self.com)
        if self.inertia is not None:
            result["inertia"] = list(self.inertia)
        if self.visual_mesh:
            result["visual_mesh"] = self.visual_mesh
        if self.collision_mesh:
            result["collision_mesh"] = self.collision_mesh
        if self.envelope:
            result["envelope"] = dict(self.envelope)
        return result

    @property
    def has_verified_mass_properties(self) -> bool:
        verified = {"source_specific", "measured"}
        return (
            self.mass_kg is not None
            and self.mass_basis in verified
            and self.com is not None
            and self.com_basis in verified
        )

    def envelope_box(self) -> Optional[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        """Return the local (min, max) corners of the screening envelope."""
        size = self.envelope.get("size")
        if not isinstance(size, Sequence) or len(size) != 3:
            return None
        origin = self.envelope.get("origin", (0.0, 0.0, 0.0))
        if not isinstance(origin, Sequence) or len(origin) != 3:
            return None
        half = tuple(abs(float(component)) / 2.0 for component in size)
        centre = tuple(float(component) for component in origin)
        return (
            tuple(centre[axis] - half[axis] for axis in range(3)),  # type: ignore[return-value]
            tuple(centre[axis] + half[axis] for axis in range(3)),
        )


@dataclass(frozen=True)
class AssemblySpec:
    """Requirements + exact components + contracts + graph + physical links.

    ``evidence`` holds externally produced verification records keyed by
    validation stage name (for example ``{"fea": [{"report": ..., "date":
    ..., "reviewer": ...}]}``).  The validation pipeline never generates that
    evidence itself — it only checks whether it is present and declared.
    """

    id: str
    title: str = ""
    description: str = ""
    schema_version: str = SPEC_SCHEMA_VERSION
    requirements: Mapping[str, Any] = field(default_factory=dict)
    variants: tuple[ComponentVariant, ...] = ()
    contracts: tuple[InterfaceContract, ...] = ()
    graph: Optional[AssemblyGraph] = None
    links: tuple[RobotLink, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any) -> "AssemblySpec":
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError as exc:
                raise AssemblySpecError("assembly spec must be a JSON object") from exc
        raw = _mapping(data, "assembly spec")
        graph_data = raw.get("graph", raw.get("assembly_graph"))
        graph: Optional[AssemblyGraph] = None
        if graph_data is not None:
            if isinstance(graph_data, AssemblyGraph):
                graph = graph_data
            else:
                try:
                    graph = parse_assembly_graph(graph_data, strict=False)
                except AssemblyGraphError as exc:
                    raise AssemblySpecError(f"graph: {exc}") from exc
        return cls(
            id=_text(raw.get("id"), "id"),
            title=_text(raw.get("title"), "title", default=""),
            description=_text(raw.get("description"), "description", default=""),
            schema_version=_text(
                raw.get("schema_version"), "schema_version", default=SPEC_SCHEMA_VERSION
            ),
            requirements=dict(_mapping(raw.get("requirements", {}), "requirements")),
            variants=tuple(
                ComponentVariant.from_dict(item, index)
                for index, item in enumerate(_list(raw.get("variants"), "variants"))
            ),
            contracts=tuple(
                InterfaceContract.from_dict(item, index)
                for index, item in enumerate(_list(raw.get("contracts"), "contracts"))
            ),
            graph=graph,
            links=tuple(
                RobotLink.from_dict(item, index)
                for index, item in enumerate(_list(raw.get("links"), "links"))
            ),
            evidence=dict(_mapping(raw.get("evidence", {}), "evidence")),
            metadata=dict(_mapping(raw.get("metadata", {}), "metadata")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "requirements": dict(self.requirements),
            "variants": [variant.to_dict() for variant in self.variants],
            "contracts": [contract.to_dict() for contract in self.contracts],
            "links": [link.to_dict() for link in self.links],
        }
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if self.graph is not None:
            result["graph"] = self.graph.to_dict()
        if self.evidence:
            result["evidence"] = dict(self.evidence)
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    def variant(self, variant_id: str) -> Optional[ComponentVariant]:
        return next((item for item in self.variants if item.id == variant_id), None)

    def contract(self, contract_id: str) -> Optional[InterfaceContract]:
        return next((item for item in self.contracts if item.id == contract_id), None)

    def link_for(self, part_instance_id: str) -> Optional[RobotLink]:
        return next(
            (item for item in self.links if item.part_instance_id == part_instance_id),
            None,
        )

    def validate(self) -> list[str]:
        """Return deterministic cross-reference errors (not release gates)."""
        errors: list[str] = []
        if self.schema_version != SPEC_SCHEMA_VERSION:
            errors.append(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {SPEC_SCHEMA_VERSION!r}"
            )
        seen_variants: set[str] = set()
        for variant in self.variants:
            if variant.id in seen_variants:
                errors.append(f"duplicate variant id {variant.id!r}")
            seen_variants.add(variant.id)
        seen_contracts: set[str] = set()
        for contract in self.contracts:
            if contract.id in seen_contracts:
                errors.append(f"duplicate contract id {contract.id!r}")
            seen_contracts.add(contract.id)

        part_ids = {part.id for part in self.graph.parts} if self.graph else set()
        seen_links: set[str] = set()
        for link in self.links:
            if link.part_instance_id in seen_links:
                errors.append(f"duplicate link for part instance {link.part_instance_id!r}")
            seen_links.add(link.part_instance_id)
            if self.graph is not None and link.part_instance_id not in part_ids:
                errors.append(
                    f"link references unknown part instance {link.part_instance_id!r}"
                )
            if link.variant_id and link.variant_id not in seen_variants:
                errors.append(
                    f"link {link.part_instance_id!r} references unknown variant "
                    f"{link.variant_id!r}"
                )
        if self.graph is not None:
            errors.extend(self.graph.validate())
        return errors


def parse_assembly_spec(data: Any, *, strict: bool = True) -> AssemblySpec:
    """Parse authoring data into an :class:`AssemblySpec`.

    ``strict=True`` raises on any cross-reference or graph error, which is
    the right boundary for LLM- or API-supplied data.
    """
    spec = data if isinstance(data, AssemblySpec) else AssemblySpec.from_dict(data)
    if strict:
        errors = spec.validate()
        if errors:
            raise AssemblySpecError(
                "AssemblySpec validation failed:\n- " + "\n- ".join(errors)
            )
    return spec


__all__ = [
    "SPEC_SCHEMA_VERSION",
    "VALUE_BASES",
    "AssemblySpecError",
    "DrawingReference",
    "ComponentVariant",
    "InterfaceContract",
    "KinematicJoint",
    "RobotLink",
    "AssemblySpec",
    "parse_assembly_spec",
]
