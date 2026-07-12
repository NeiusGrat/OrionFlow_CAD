# Mechanical Knowledge Layer

This directory is OrionFlow's versioned mechanical-engineering knowledge
package. It is deliberately separate from model weights and document dumps:
the agent retrieves concise, traceable knowledge items and uses deterministic
calculators for numeric work.

## v0.1 scope

- GD&T terminology and drawing-governance guidance.
- Sheet-metal fundamentals: bend calculations and DFM screening guidance.
- Source and licensing metadata for the provided Drafter references, ASME,
  ISO, and NIST references.

The original third-party PDFs and image are **not** committed here. Their
contents are represented only by short, attributable knowledge items. Keep any
licensed or copyrighted originals in access-controlled document storage.

## Authority model

Every item has an `authority`, `maturity`, and source reference:

- `normative_reference`: a catalogued official standard. The standard text is
  not embedded; use requires a licensed copy and engineer review.
- `secondary_reference`: learning or vendor guidance; never describe it as a
  compliance requirement.
- `screening_guideline`: useful deterministic DFM warning, but not a supplier
  approval or a release decision.

No source becomes a hard production rule until a qualified engineer approves
its scope, revision, and implementation.

## Adding knowledge

1. Add a source record to `sources.json`, including publisher, revision, URL or
   controlled-document identifier, license status, and verification date.
2. Add a small, paraphrased knowledge item to `knowledge.json` with conditions,
   units, authority, and an engineering-review state.
3. Put calculations in `orion_agent/harness/mechanical_knowledge.py`, with
   independent unit tests in `tests/test_mechanical_knowledge.py`.
4. Do not copy tables or full standards into the repository unless the project
   has explicit redistribution rights.

## Roadmap

1. v0.1 - drawing and sheet-metal fundamentals (this package).
2. v0.2 - thread series, fasteners, standard holes, materials, and process
   capability profiles tied to exact source revisions.
3. v0.3 - fits/tolerances, tolerance stack-up, bolted-joint and beam/plate
   calculators with engineer-approved assumptions.
4. v0.4 - bearings, shafts, gears, fatigue, and safety-factor workflows.
5. v1.0 - supplier-specific manufacturing rules, FEA/test evidence, change
   management, and digital-thread links to CAD, inspection, and quality data.
