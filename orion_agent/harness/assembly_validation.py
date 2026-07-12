"""Ordered, deterministic validation pipeline for :class:`AssemblySpec`.

The stages run in the fixed engineering order and each produces a typed
report:

1. ``geometry`` — graph structure, frames, and per-part geometry basis
2. ``interfaces_mates`` — contract coverage, mate/joint consistency, mobility
3. ``dfm`` — design-for-manufacturing screening of declared custom parts
4. ``closed_form`` — declared screening calculations (belt, screw, torque)
5. ``collision_kinematics`` — rooted-tree kinematics + envelope interference
6. ``mass_cog`` — assembly mass and centre of gravity with provenance
7. ``fea`` — presence of externally produced, attached FEA evidence

Every stage is deterministic and stdlib-only.  Stages never invent inputs:
missing data yields ``evidence_required``, never a silent pass.  A stage that
cannot run because an earlier stage failed reports ``blocked``.  Nothing here
is a release approval — the pipeline reports screening status and the exact
evidence still owed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Mapping, Optional, Sequence

from orion_agent.harness.assembly_graph import AssemblyGraph, Joint
from orion_agent.harness.assembly_spec import AssemblySpec, parse_assembly_spec
from orion_agent.harness.urdf_export import validate_urdf_export

STAGE_ORDER = (
    "geometry",
    "interfaces_mates",
    "dfm",
    "closed_form",
    "collision_kinematics",
    "mass_cog",
    "fea",
)

# Worst-first ordering used to combine finding statuses into a stage status
# and stage statuses into the overall pipeline status.
_STATUS_SEVERITY = ("failed", "blocked", "evidence_required", "warning", "passed", "skipped")

_GRAVITY_M_S2 = 9.80665
_VERIFIED_BASES = {"source_specific", "measured"}


@dataclass
class StageReport:
    """One validation stage's outcome."""

    name: str
    status: str = "passed"
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, message: str, **extra: Any) -> None:
        finding = {"status": status, "message": message}
        finding.update(extra)
        self.findings.append(finding)

    def finalize(self, default_summary: str) -> "StageReport":
        statuses = [finding["status"] for finding in self.findings] or ["passed"]
        self.status = min(statuses, key=_STATUS_SEVERITY.index)
        if not self.summary:
            self.summary = default_summary
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "status": self.status,
            "summary": self.summary,
            "findings": list(self.findings),
        }


def run_validation(data: Any) -> dict[str, Any]:
    """Run every stage in order and return a JSON-ready pipeline report."""
    spec = data if isinstance(data, AssemblySpec) else parse_assembly_spec(data, strict=False)
    stages: list[StageReport] = []

    geometry = _stage_geometry(spec)
    stages.append(geometry)
    stages.append(_stage_interfaces_mates(spec, blocked=geometry.status == "failed"))
    stages.append(_stage_dfm(spec))
    stages.append(_stage_closed_form(spec))
    kinematics_ready = geometry.status != "failed"
    stages.append(_stage_collision_kinematics(spec, blocked=not kinematics_ready))
    stages.append(_stage_mass_cog(spec, blocked=not kinematics_ready))
    stages.append(_stage_fea(spec))

    overall = min((stage.status for stage in stages), key=_STATUS_SEVERITY.index)
    return {
        "spec_id": spec.id,
        "pipeline": "orion_assembly_validation_v1",
        "order": list(STAGE_ORDER),
        "overall": overall,
        "stages": [stage.to_dict() for stage in stages],
        "limitations": [
            "Screening pipeline only: it checks declared data and deterministic "
            "models, not physical hardware, supplier approval, or safety.",
            "evidence_required findings list the verification work still owed "
            "before any release claim.",
        ],
    }


def render_validation(result: Mapping[str, Any]) -> str:
    """Render a pipeline report for an LLM tool observation."""
    lines = [
        f"Assembly validation pipeline for {result.get('spec_id', '?')!r}: "
        f"overall={result.get('overall', '?')}",
    ]
    for stage in result.get("stages", []):
        lines.append(f"[{stage['status']}] {stage['stage']}: {stage['summary']}")
        for finding in stage.get("findings", []):
            if finding["status"] != "passed":
                lines.append(f"  - {finding['status']}: {finding['message']}")
    lines.append("Limitations: " + " ".join(result.get("limitations", [])))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stage 1: geometry
# --------------------------------------------------------------------------- #
def _stage_geometry(spec: AssemblySpec) -> StageReport:
    report = StageReport("geometry")
    if spec.graph is None:
        report.add("failed", "spec has no AssemblyGraph")
        return report.finalize("no assembly graph")
    for error in spec.graph.validate():
        report.add("failed", error)
    for error in spec.validate():
        # Graph errors already reported above; keep only spec-level ones.
        if error not in {finding["message"] for finding in report.findings}:
            report.add("failed", error)
    for part in spec.graph.parts:
        link = spec.link_for(part.id)
        has_geometry = bool(part.definition) or (
            link is not None and (link.envelope or link.visual_mesh or link.collision_mesh)
        )
        if not has_geometry:
            report.add(
                "evidence_required",
                f"part {part.id!r} has no geometry basis (definition, envelope, or mesh)",
                part_instance=part.id,
            )
    return report.finalize(
        f"{len(spec.graph.parts)} part(s) checked; graph structure and frames valid"
        if not report.findings else "geometry issues found"
    )


# --------------------------------------------------------------------------- #
# Stage 2: interfaces and mates
# --------------------------------------------------------------------------- #
def _stage_interfaces_mates(spec: AssemblySpec, *, blocked: bool) -> StageReport:
    report = StageReport("interfaces_mates")
    if blocked:
        report.add("blocked", "geometry stage failed; interface review not meaningful")
        return report.finalize("blocked by geometry stage")
    graph = spec.graph
    assert graph is not None  # blocked path handles the None case
    contract_ids = {contract.id for contract in spec.contracts}
    for interface in graph.interfaces:
        declared = interface.metadata.get("contract")
        if declared is None:
            report.add(
                "warning",
                f"interface {interface.id!r} declares no InterfaceContract "
                "(metadata.contract); its mating requirements are untracked",
                interface=interface.id,
            )
        elif declared not in contract_ids:
            report.add(
                "failed",
                f"interface {interface.id!r} references unknown contract {declared!r}",
                interface=interface.id,
            )
    for contract in spec.contracts:
        if contract.data_status != "source_specific":
            report.add(
                "evidence_required",
                f"contract {contract.id!r} is {contract.data_status}; resolve it "
                "against the exact selected drawing before dimensioning",
                contract=contract.id,
            )
    mobility = graph.mobility_estimate()
    expected = spec.requirements.get("expected_dof")
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if mobility["estimated_dof"] != expected:
            report.add(
                "warning",
                f"Gruebler screening mobility {mobility['estimated_dof']} differs "
                f"from required expected_dof {int(expected)}; review constraints",
                mobility=mobility,
            )
        else:
            report.add(
                "passed",
                f"screening mobility matches expected_dof={int(expected)}",
                mobility=mobility,
            )
    return report.finalize(
        f"{len(graph.interfaces)} interface(s), {len(graph.mates)} mate(s), "
        f"{len(graph.joints)} joint(s) reviewed"
    )


# --------------------------------------------------------------------------- #
# Stage 3: DFM
# --------------------------------------------------------------------------- #
def _stage_dfm(spec: AssemblySpec) -> StageReport:
    report = StageReport("dfm")
    graph = spec.graph
    custom_parts = []
    for part in graph.parts if graph is not None else ():
        link = spec.link_for(part.id)
        is_purchased = bool(link is not None and link.variant_id) or (
            part.definition.get("kind") in {"robotics_component", "purchased_component"}
        )
        if not is_purchased:
            custom_parts.append(part)
    if not custom_parts:
        report.add("skipped", "no custom parts declared; DFM applies to custom fabrication")
        return report.finalize("no custom parts")
    for part in custom_parts:
        dfm = part.metadata.get("dfm")
        if not isinstance(dfm, Mapping):
            report.add(
                "evidence_required",
                f"custom part {part.id!r} declares no DFM data "
                "(metadata.dfm with process and dimensions)",
                part_instance=part.id,
            )
            continue
        process = str(dfm.get("process", ""))
        if process == "sheet_metal":
            _sheet_metal_screen(part.id, dfm, report)
        else:
            report.add(
                "evidence_required",
                f"custom part {part.id!r} process {process or 'unspecified'!r} has no "
                "packaged screening; attach supplier DFM review evidence",
                part_instance=part.id,
            )
    return report.finalize(f"{len(custom_parts)} custom part(s) screened")


def _sheet_metal_screen(part_id: str, dfm: Mapping[str, Any], report: StageReport) -> None:
    from orion_agent.harness import mechanical_knowledge as mk

    kwargs = {
        key: dfm.get(key)
        for key in (
            "thickness_mm", "inside_radius_mm", "hole_diameter_mm", "hole_spacing_mm",
            "hole_edge_distance_mm", "bend_relief_width_mm", "bend_relief_depth_mm",
        )
        if dfm.get(key) is not None
    }
    try:
        result = mk.check_sheet_metal_dfm(**kwargs)
    except mk.KnowledgeInputError as exc:
        report.add("failed", f"custom part {part_id!r} sheet-metal DFM inputs invalid: {exc}",
                   part_instance=part_id)
        return
    status_map = {"screening_passed": "passed", "needs_attention": "warning",
                  "review_required": "evidence_required"}
    report.add(
        status_map.get(result["overall"], "warning"),
        f"custom part {part_id!r} sheet-metal screening: {result['overall']}",
        part_instance=part_id,
        checks=result["checks"],
    )


# --------------------------------------------------------------------------- #
# Stage 4: closed-form calculations
# --------------------------------------------------------------------------- #
def _stage_closed_form(spec: AssemblySpec) -> StageReport:
    report = StageReport("closed_form")
    declared = spec.requirements.get("calculations")
    if not isinstance(declared, list) or not declared:
        report.add(
            "evidence_required",
            "no closed-form calculations declared in requirements.calculations; "
            "sizing evidence is owed before any load or motion claim",
        )
        return report.finalize("no calculations declared")
    for index, calc in enumerate(declared):
        if not isinstance(calc, Mapping):
            report.add("failed", f"calculations[{index}] must be an object")
            continue
        kind = str(calc.get("type", ""))
        handler = _CALCULATORS.get(kind)
        if handler is None:
            report.add(
                "evidence_required",
                f"calculations[{index}] type {kind!r} has no packaged screening "
                f"model (available: {', '.join(sorted(_CALCULATORS))}); attach "
                "an external calculation record",
            )
            continue
        try:
            handler(calc, report)
        except (TypeError, ValueError) as exc:
            report.add("failed", f"calculations[{index}] ({kind}) invalid inputs: {exc}")
    return report.finalize(f"{len(declared)} declared calculation(s) processed")


def _num(calc: Mapping[str, Any], key: str) -> float:
    value = calc.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{key} must be finite and positive")
    return number


def _margin_status(margin: float, screening_factor: float) -> str:
    if margin < 1.0:
        return "failed"
    if margin < screening_factor:
        return "warning"
    return "passed"


def _calc_belt_axis(calc: Mapping[str, Any], report: StageReport) -> None:
    """Screen a belt-driven axis: motor torque vs. accelerating the payload.

    ``F = m * (a + mu * g)`` and ``T = F * r`` with the pulley pitch radius.
    Belt tension distribution, inertia of rotating parts, efficiency, and
    vendor tooth-load limits are intentionally out of scope: the supplier
    sizing method remains a separate evidence gate.
    """
    mass = _num(calc, "moving_mass_kg")
    acceleration = _num(calc, "acceleration_m_s2")
    radius_m = _num(calc, "pulley_pitch_radius_mm") / 1000.0
    torque_available = _num(calc, "motor_torque_nm")
    friction = float(calc.get("friction_coefficient", 0.0) or 0.0)
    factor = float(calc.get("screening_factor", 2.0) or 2.0)
    force = mass * (acceleration + friction * _GRAVITY_M_S2)
    torque_required = force * radius_m
    margin = torque_available / torque_required if torque_required > 0 else math.inf
    report.add(
        _margin_status(margin, factor),
        f"belt axis screening: required torque {torque_required:.4f} N*m vs "
        f"available {torque_available:.4f} N*m (margin {margin:.2f}, screening "
        f"factor {factor:g}); supplier belt sizing still required",
        calculation="belt_axis_screening",
        required_torque_nm=torque_required,
        available_torque_nm=torque_available,
        margin=margin,
    )


def _calc_leadscrew_grip(calc: Mapping[str, Any], report: StageReport) -> None:
    """Screen lead-screw jaw force: ``F = 2*pi*eta*T / lead`` split across jaws."""
    torque = _num(calc, "motor_torque_nm")
    lead_m = _num(calc, "screw_lead_mm") / 1000.0
    efficiency = _num(calc, "efficiency")
    if efficiency > 1.0:
        raise ValueError("efficiency must be at most 1")
    required = _num(calc, "required_grip_force_n")
    jaws = int(calc.get("jaw_count", 2) or 2)
    factor = float(calc.get("screening_factor", 2.0) or 2.0)
    axial_force = 2.0 * math.pi * efficiency * torque / lead_m
    per_jaw = axial_force / max(jaws, 1)
    margin = per_jaw / required if required > 0 else math.inf
    report.add(
        _margin_status(margin, factor),
        f"lead-screw grip screening: {per_jaw:.1f} N per jaw vs required "
        f"{required:.1f} N (margin {margin:.2f}); friction, buckling, and wear "
        "analyses remain separate evidence",
        calculation="leadscrew_grip_screening",
        per_jaw_force_n=per_jaw,
        required_force_n=required,
        margin=margin,
    )


def _calc_actuator_torque(calc: Mapping[str, Any], report: StageReport) -> None:
    """Screen geared output torque against the load, capped by gear limits."""
    motor_torque = _num(calc, "motor_torque_nm")
    ratio = _num(calc, "gear_ratio")
    efficiency = _num(calc, "efficiency")
    if efficiency > 1.0:
        raise ValueError("efficiency must be at most 1")
    required = _num(calc, "required_output_torque_nm")
    factor = float(calc.get("screening_factor", 2.0) or 2.0)
    output = motor_torque * ratio * efficiency
    rated_limit = calc.get("gear_rated_torque_nm")
    notes = ""
    if isinstance(rated_limit, (int, float)) and not isinstance(rated_limit, bool):
        if output > float(rated_limit):
            notes = (
                f"; geared output {output:.1f} N*m exceeds the gear rated torque "
                f"{float(rated_limit):.1f} N*m — output is gear-limited"
            )
            output = float(rated_limit)
    margin = output / required if required > 0 else math.inf
    report.add(
        _margin_status(margin, factor),
        f"actuator torque screening: usable output {output:.2f} N*m vs required "
        f"{required:.2f} N*m (margin {margin:.2f}){notes}; duty-cycle, thermal, "
        "and life calculations remain separate evidence",
        calculation="actuator_torque_screening",
        output_torque_nm=output,
        required_torque_nm=required,
        margin=margin,
    )


_CALCULATORS: dict[str, Callable[[Mapping[str, Any], StageReport], None]] = {
    "belt_axis_screening": _calc_belt_axis,
    "leadscrew_grip_screening": _calc_leadscrew_grip,
    "actuator_torque_screening": _calc_actuator_torque,
}


# --------------------------------------------------------------------------- #
# Stage 5: collision / kinematics
# --------------------------------------------------------------------------- #
def _stage_collision_kinematics(spec: AssemblySpec, *, blocked: bool) -> StageReport:
    report = StageReport("collision_kinematics")
    if blocked:
        report.add("blocked", "geometry stage failed; kinematic checks not meaningful")
        return report.finalize("blocked by geometry stage")
    graph = spec.graph
    assert graph is not None
    urdf_errors = validate_urdf_export(graph)
    for error in urdf_errors:
        report.add("failed", f"kinematic tree: {error}")
    if urdf_errors:
        return report.finalize("kinematic tree invalid; collision screening skipped")

    missing = [part.id for part in graph.parts
               if (link := spec.link_for(part.id)) is None or link.envelope_box() is None]
    if missing:
        report.add(
            "evidence_required",
            "no screening envelope for part(s): " + ", ".join(sorted(missing))
            + "; interference screening incomplete",
        )
    overlaps = _screen_envelope_interference(spec, graph)
    for overlap in overlaps:
        report.add(
            "warning",
            f"screening envelopes of {overlap['part_a']!r} and {overlap['part_b']!r} "
            f"overlap at pose {overlap['pose']} (~{overlap['penetration_mm']:.2f} mm); "
            "check real geometry for interference",
            **overlap,
        )
    if not missing and not overlaps:
        report.add("passed", "no envelope interference between non-mated parts at sampled poses")
    return report.finalize("kinematic tree valid; envelope screening complete")


def _rpy_matrix(rpy: Sequence[float]) -> tuple[tuple[float, float, float], ...]:
    roll, pitch, yaw = (float(component) for component in rpy)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # URDF fixed-axis convention: R = Rz(yaw) * Ry(pitch) * Rx(roll)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _axis_angle_matrix(axis: Sequence[float], angle: float) -> tuple[tuple[float, float, float], ...]:
    x, y, z = (float(component) for component in axis)
    norm = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / norm, y / norm, z / norm
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return (
        (t * x * x + c, t * x * y - s * z, t * x * z + s * y),
        (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
        (t * x * z - s * y, t * y * z + s * x, t * z * z + c),
    )


def _mat_mul(a, b):
    return tuple(
        tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3))
        for row in range(3)
    )


def _mat_vec(m, v):
    return tuple(sum(m[row][k] * v[k] for k in range(3)) for row in range(3))


@dataclass(frozen=True)
class _Pose:
    rotation: tuple[tuple[float, float, float], ...]
    translation: tuple[float, float, float]

    def compose(self, other: "_Pose") -> "_Pose":
        return _Pose(
            rotation=_mat_mul(self.rotation, other.rotation),
            translation=tuple(
                self.translation[i] + _mat_vec(self.rotation, other.translation)[i]
                for i in range(3)
            ),
        )


_IDENTITY = _Pose(((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.0, 0.0, 0.0))


def _neutral_value(joint: Joint) -> float:
    limits = joint.limits
    if limits is None or limits.lower is None or limits.upper is None:
        return 0.0
    return min(max(0.0, limits.lower), limits.upper)


def _joint_pose(joint: Joint, value: float) -> _Pose:
    origin = joint.metadata.get("urdf_origin", {})
    xyz = tuple(float(c) for c in origin.get("xyz", (0, 0, 0)))
    rpy = tuple(float(c) for c in origin.get("rpy", (0, 0, 0)))
    pose = _Pose(_rpy_matrix(rpy), xyz)
    if joint.kind == "revolute" and joint.axis is not None:
        pose = pose.compose(_Pose(_axis_angle_matrix(joint.axis, value), (0.0, 0.0, 0.0)))
    elif joint.kind == "prismatic" and joint.axis is not None:
        norm = math.sqrt(sum(component * component for component in joint.axis))
        offset = tuple(component / norm * value for component in joint.axis)
        pose = pose.compose(_Pose(_IDENTITY.rotation, offset))
    return pose


def _link_poses(graph: AssemblyGraph, joint_values: Mapping[str, float]) -> dict[str, _Pose]:
    """Place every part with the URDF chaining convention at given joint values."""
    interfaces = {interface.id: interface for interface in graph.interfaces}
    children: dict[str, list[Joint]] = {}
    child_parts = set()
    for joint in graph.joints:
        parent = interfaces[joint.parent_interface].part_id
        child = interfaces[joint.child_interface].part_id
        children.setdefault(parent, []).append(joint)
        child_parts.add(child)
    roots = [part.id for part in graph.parts if part.id not in child_parts]
    poses: dict[str, _Pose] = {}
    stack = [(root, _IDENTITY) for root in roots]
    while stack:
        part_id, pose = stack.pop()
        poses[part_id] = pose
        for joint in children.get(part_id, ()):
            child = interfaces[joint.child_interface].part_id
            value = joint_values.get(joint.id, _neutral_value(joint))
            stack.append((child, pose.compose(_joint_pose(joint, value))))
    return poses


def _world_aabb(link_box, pose: _Pose):
    (min_corner, max_corner) = link_box
    corners = [
        (x, y, z)
        for x in (min_corner[0], max_corner[0])
        for y in (min_corner[1], max_corner[1])
        for z in (min_corner[2], max_corner[2])
    ]
    world = [
        tuple(pose.translation[i] + _mat_vec(pose.rotation, corner)[i] for i in range(3))
        for corner in corners
    ]
    return (
        tuple(min(point[axis] for point in world) for axis in range(3)),
        tuple(max(point[axis] for point in world) for axis in range(3)),
    )


def _mated_pairs(graph: AssemblyGraph) -> set[frozenset[str]]:
    interfaces = {interface.id: interface for interface in graph.interfaces}
    pairs: set[frozenset[str]] = set()
    for joint in graph.joints:
        pairs.add(frozenset((
            interfaces[joint.parent_interface].part_id,
            interfaces[joint.child_interface].part_id,
        )))
    for mate in graph.mates:
        side_a = interfaces.get(mate.interface_a)
        side_b = interfaces.get(mate.interface_b)
        if side_a is not None and side_b is not None:
            pairs.add(frozenset((side_a.part_id, side_b.part_id)))
    return pairs


def _sample_poses(graph: AssemblyGraph) -> list[tuple[str, dict[str, float]]]:
    """Neutral pose plus each movable joint at its lower and upper limit."""
    samples: list[tuple[str, dict[str, float]]] = [("neutral", {})]
    for joint in graph.joints:
        if joint.kind not in {"revolute", "prismatic"} or joint.limits is None:
            continue
        if joint.limits.lower is not None:
            samples.append((f"{joint.id}=lower", {joint.id: joint.limits.lower}))
        if joint.limits.upper is not None:
            samples.append((f"{joint.id}=upper", {joint.id: joint.limits.upper}))
    return samples[:24]  # deterministic cap


def _screen_envelope_interference(spec: AssemblySpec, graph: AssemblyGraph) -> list[dict[str, Any]]:
    boxes = {}
    for part in graph.parts:
        link = spec.link_for(part.id)
        box = link.envelope_box() if link is not None else None
        if box is not None:
            boxes[part.id] = box
    if len(boxes) < 2:
        return []
    allowed = _mated_pairs(graph)
    overlaps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pose_name, values in _sample_poses(graph):
        placed = _link_poses(graph, values)
        world = {
            part_id: _world_aabb(box, placed[part_id])
            for part_id, box in boxes.items()
            if part_id in placed
        }
        ids = sorted(world)
        for i, part_a in enumerate(ids):
            for part_b in ids[i + 1:]:
                if frozenset((part_a, part_b)) in allowed:
                    continue
                if (part_a, part_b) in seen:
                    continue
                pen = _aabb_penetration(world[part_a], world[part_b])
                if pen > 1e-6:
                    seen.add((part_a, part_b))
                    overlaps.append({
                        "part_a": part_a,
                        "part_b": part_b,
                        "pose": pose_name,
                        "penetration_mm": pen,
                    })
    return overlaps


def _aabb_penetration(box_a, box_b) -> float:
    penetration = math.inf
    for axis in range(3):
        overlap = min(box_a[1][axis], box_b[1][axis]) - max(box_a[0][axis], box_b[0][axis])
        if overlap <= 0:
            return 0.0
        penetration = min(penetration, overlap)
    return penetration


# --------------------------------------------------------------------------- #
# Stage 6: mass / CoG
# --------------------------------------------------------------------------- #
def _stage_mass_cog(spec: AssemblySpec, *, blocked: bool) -> StageReport:
    report = StageReport("mass_cog")
    if blocked:
        report.add("blocked", "geometry stage failed; mass rollup not meaningful")
        return report.finalize("blocked by geometry stage")
    graph = spec.graph
    assert graph is not None
    total_mass = 0.0
    weighted = [0.0, 0.0, 0.0]
    missing: list[str] = []
    unverified: list[str] = []
    poses = _link_poses(graph, {}) if not validate_urdf_export(graph) else {}
    for part in graph.parts:
        link = spec.link_for(part.id)
        if link is None or link.mass_kg is None:
            missing.append(part.id)
            continue
        if link.mass_basis not in _VERIFIED_BASES:
            unverified.append(f"{part.id} (mass_basis={link.mass_basis})")
        total_mass += link.mass_kg
        com = link.com or (0.0, 0.0, 0.0)
        pose = poses.get(part.id, _IDENTITY)
        world_com = tuple(
            pose.translation[i] + _mat_vec(pose.rotation, com)[i] for i in range(3)
        )
        for axis in range(3):
            weighted[axis] += link.mass_kg * world_com[axis]
        if link.com is not None and link.com_basis not in _VERIFIED_BASES:
            unverified.append(f"{part.id} (com_basis={link.com_basis})")
    if missing:
        report.add(
            "evidence_required",
            "no mass declared for part(s): " + ", ".join(sorted(missing)),
        )
    if unverified:
        report.add(
            "evidence_required",
            "mass properties not verified for: " + ", ".join(sorted(set(unverified)))
            + "; only source_specific or measured values count as verified",
        )
    if total_mass > 0:
        cog = [value / total_mass for value in weighted]
        basis = "verified" if not (missing or unverified) else "partial_unverified"
        report.add(
            "passed" if basis == "verified" else "warning",
            f"assembly mass rollup {total_mass:.4f} kg, CoG at "
            f"({cog[0]:.2f}, {cog[1]:.2f}, {cog[2]:.2f}) {graph.units} "
            f"[{basis}] at neutral pose",
            total_mass_kg=total_mass,
            cog=cog,
            basis=basis,
        )
    return report.finalize("mass and centre-of-gravity rollup complete")


# --------------------------------------------------------------------------- #
# Stage 7: FEA
# --------------------------------------------------------------------------- #
def _stage_fea(spec: AssemblySpec) -> StageReport:
    report = StageReport("fea")
    records = spec.evidence.get("fea")
    if not isinstance(records, list) or not records:
        report.add(
            "evidence_required",
            "no FEA evidence attached (spec.evidence.fea); structural verification "
            "is owed for load-bearing custom parts before release",
        )
        return report.finalize("no FEA evidence")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            report.add("failed", f"evidence.fea[{index}] must be an object")
            continue
        missing = [key for key in ("report", "date", "reviewer") if not record.get(key)]
        if missing:
            report.add(
                "evidence_required",
                f"evidence.fea[{index}] incomplete; missing: " + ", ".join(missing),
            )
        else:
            report.add(
                "passed",
                f"FEA evidence attached: {record['report']} "
                f"({record['date']}, reviewer {record['reviewer']}); the pipeline "
                "records its presence and does not judge its content",
            )
    return report.finalize(f"{len(records)} FEA evidence record(s) reviewed")


__all__ = [
    "STAGE_ORDER",
    "StageReport",
    "run_validation",
    "render_validation",
]
