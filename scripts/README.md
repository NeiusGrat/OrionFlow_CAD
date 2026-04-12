# Build123d-FTC Dataset Pipeline

Scripts for generating the Build123d Feature Tree Convention (FTC) fine-tuning dataset.

## Pipeline Phases (run in order)

| Phase | Script | Description |
|-------|--------|-------------|
| P1 | `p1_template_generator.py` | Generate parametric Build123d-FTC training data from 30 templates |
| P2 | `p2_convert_deepcad_to_b123d.py` | Convert raw DeepCAD JSON → Build123d-FTC training samples |
| P3 | `p3_generate_edit_samples.py` | Generate editing/modification training pairs |
| P4 | `p4_generate_complex_examples.py` | Generate complex multi-feature training examples |
| P5 | `p5_generate_rejections.py` | Generate refusal/clarification training samples |
| P6 | `p6_assemble_final_dataset.py` | Merge, deduplicate, split into train/val/test |

## Validation Scripts

| Script | Description |
|--------|-------------|
| `validate_build123d.py` | Validate Build123d code samples via subprocess execution |
| `validate_all_templates.py` | Validate all parametric templates produce valid geometry |
| `run_full_validation.py` | Run the full validation pipeline end-to-end |

## Conversion Utilities

| Script | Description |
|--------|-------------|
| `cq_to_ofl.py` | CadQuery → OFL transpiler (AST-based) |
| `ofl_to_b123d.py` | OFL → Build123d-FTC converter |

## Infrastructure

| Script | Description |
|--------|-------------|
| `init-db.sql` | PostgreSQL schema initialization |
| `start.sh` | Production server start script |

## Output

Final dataset lands in `data/build123d_ftc/final/`:
- `train.jsonl` — training split
- `val.jsonl` — validation split
- `test.jsonl` — test split
- `manifest.json` — dataset metadata
