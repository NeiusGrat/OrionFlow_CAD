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

## NASA rule graph (`nasa_rules.json`)

705 requirements transcribed **verbatim** from eight public-domain NASA
Technical Standards. Unlike the licensed ASME/ISO material above, NASA
standards are works of the US Government, so the requirement text itself can
be stored and quoted here.

| Standard | Tag | Domain | Rules |
|---|---|---|---|
| NASA-STD-5001B | `FSR` | structural margins / factors of safety | 61 |
| NASA-STD-5002B | `LAR` | load analyses | 67 |
| NASA-STD-5006A | `GWR` | welding | 142 |
| NASA-STD-5009C | `NER` | nondestructive evaluation | 74 |
| NASA-STD-5017B | `DDMR` | mechanisms | 90 |
| NASA-STD-5019A | `FCR` | fracture control | 26 |
| NASA-STD-5020B | `TFSR` | threaded fastening systems | 32 |
| NASA-STD-6016C | `MPR` | materials and processes | 213 |

Every rule carries `standard + revision + requirement_tag + section + page`,
so any statement the agent surfaces can be checked against the source PDF.
99.9% of statements were verified to occur on the page they cite (the single
exception spans a page break; its citation is still correct).

Rebuild with `python scripts/build_nasa_rule_graph.py` (needs `pypdf` and
network; source PDFs cache to the gitignored `data/nasa_standards/`). Validate
the committed graph offline with `--check`. Read it at runtime through
`orion_agent/harness/nasa_rules.py`, or the `lookup_nasa_requirement` tool.

The extractor never paraphrases and never guesses: a requirement that does not
parse into a well-formed normative statement is dropped rather than repaired.

**Scope limit.** These requirements bind *NASA spaceflight hardware*. They are
strong engineering defaults and are not a compliance claim about a user's part;
`render()` attaches that caveat to every result and the pillar policy repeats it.

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
