# Robotics Knowledge Layer

This package is OrionFlow's source-aware, versioned starting point for
robotics assemblies. It describes reusable components, interface contracts,
and assembly demonstrations without pretending that an illustrative CAD
configuration is a release-ready robot.

It complements the mechanical knowledge package. The mechanical package holds
engineering rules and calculations; this package holds the robot-specific
objects and relationships that a CAD/assembly agent needs to retrieve before
generating geometry, a BOM, or a robot-description artifact.

## v0.1 scope

The first four demonstration assemblies reuse the same component and interface
vocabulary:

1. NEMA 23 belt-driven linear axis.
2. Electric parallel-jaw gripper.
3. Two-axis camera or LiDAR pan-tilt head.
4. Modular BLDC plus strain-wave actuator.

Each demo is deliberately an **engineering concept package**, not a claim that
the named combination is safe, manufacturable, or compatible. It gives the
agent a bounded, traceable starting point for a real multi-part CAD assembly.

## Files

- `sources.json` — official, vendor, and licensed-reference metadata.
- `components.json` — purchased-part candidates, source-specific catalogue
  records, and custom-part concepts.
- `interfaces.json` — contracts for mechanical, kinematic, electrical,
  feedback, and cable-routing connections.
- `demos.json` — assembly graphs, kinematic intent, required inputs, evidence
  gates, and expected exports.
- `schemas/` — JSON Schemas for the three data files.

No supplier CAD, datasheets, drawings, standard text, or third-party models are
committed here. Retrieve those only from the licensed or official source named
by a record and retain its revision with the generated assembly.

## Data-status policy

Every component and interface has one of these statuses:

- `source_specific` — a concise claim tied to an exact source record. It is
  still subject to the supplier drawing revision and engineering review.
- `candidate` — a family or procurement direction. It is **not** a selected
  part, and dimensions, ratings, pin-outs, fits, and mounting patterns must be
  obtained from the exact model's controlled drawing.
- `illustrative` — topology or geometry intent only. It must never populate a
  release BOM or be used to calculate safety, load, torque, or tolerance
  margins.

No record in v0.1 is engineering-approved. The agent must surface the
`data_status`, source IDs, and review requirements whenever it retrieves or
uses a record.

## Agent workflow

1. Select a demo or accept a validated `RobotAssemblySpec`.
2. Resolve every component and interface reference.
3. Stop for an exact manufacturer part number, drawing revision, material,
   payload, duty cycle, environment, and safety context whenever a candidate
   would affect the result.
4. Create the AssemblyGraph and per-part FeatureGraphs.
5. Generate CAD only with explicit datum frames and interface contracts.
6. Verify geometry, mates, collision, kinematics, mass/CoG, DFM, and
   source/revision completeness before declaring an output usable.
7. Export only verified artifacts: FCStd, STEP, BOM, URDF/Xacro, collision
   meshes, and GLB/USD as applicable.

## Representation rules

- Use millimetres, kilograms, newtons, newton-metres, seconds, radians, and
  SI-derived units in generated calculations unless a source explicitly uses a
  different unit and the conversion is recorded.
- A `source_specific` numeric claim must carry both `basis: source_specific`
  and a local source ID.
- Do not silently replace a source-specific item with a look-alike part.
- A frame contract must state its origin, axes, handedness, parent frame, and
  verification method before it is used in a mate or URDF joint.
- `URDF` describes a kinematic tree. Closed loops, belts, and paired jaws may
  need a simulator-specific constraint or a clearly documented mimic-joint
  approximation.
- Treat ISO/IEC/ASME references as catalogue metadata unless the project has
  licensed access and a qualified engineer has reviewed the implementation.

## Roadmap

1. **v0.1 (this package):** reusable assembly vocabulary and four demo graphs.
2. **v0.2:** exact approved supplier models, controlled drawings, mass and
   inertia properties, fasteners, cable/connectors, and supplier capability
   profiles.
3. **v0.3:** actuator sizing, belt/lead-screw calculations, bearing/shaft
   selection, configuration management, and verified URDF/Xacro exports.
4. **v0.4:** collision envelopes, wiring harnesses, calibration interfaces,
   simulation evidence, and serviceability checks.
5. **v1.0:** requirements-to-verification traceability, released BOMs,
   inspection evidence, change control, and approved design templates.

## Safety and authority boundary

This is a design-assistance knowledge layer. It does not replace a risk
assessment, guarding and functional-safety design, actuator sizing, electrical
safety review, supplier approval, or a licensed standard. The agent must not
describe any demo as safe for people, compliant, production-ready, or suitable
for a stated payload until the required evidence exists.
