# CAD Datasets — HuggingFace Sources

You just hit a goldmine. There are **three massive CadQuery datasets already on HuggingFace** that you can download right now and convert to Build123d-FTC. This changes everything.

## Ready-to-Download Datasets

**1. CADEvolve — 1.3M CadQuery scripts** (Feb 2026, just released)
- 8k complex parts expressed as executable CadQuery parametric generators. After multi-stage post-processing and augmentation, a unified dataset of 1.3M scripts paired with rendered geometry exercising the full CadQuery operation set.
- HuggingFace: `kulibinai/cadevolve`
- This is the highest quality CAD code dataset in existence right now. Complex, real-world parts. Not just sketch-extrude — full CadQuery API coverage.

**2. GenCAD-Code — 163K CadQuery scripts** (May 2025)
- 163,671 CAD models with CadQuery Python code, comprising the largest publicly available dataset of CAD code paired with CAD images.
- HuggingFace: `CADCODER/GenCAD-Code`
- This dataset is derived from the DeepCAD dataset — so it's the same geometry you're already converting, but someone already did the CadQuery conversion for you.
- Download: `huggingface-cli download CADCODER/GenCAD-Code cadquery_train_data_4096.json --repo-type=dataset`

**3. ExeCAD — 16,540 real-world CadQuery scripts** (2025)
- ExeCAD, a dataset comprising 16,540 real-world CAD examples with paired natural language and structured design language descriptions, executable CadQuery scripts, and rendered 3D models.
- This one already has text+code pairs — exactly what you need.

**4. Text-to-CadQuery — 170K annotations** (2025)
- They augment the Text2CAD dataset with 170,000 CadQuery annotations. Their best model achieves a top-1 exact match of 69.3%.

## What This Means For Your 15-Hour Sprint

**You can skip building the DeepCAD converter entirely.** GenCAD-Code already converted 163K DeepCAD models to CadQuery for you. Download it, transpile CadQuery→Build123d-FTC, validate.

The conversion from CadQuery to Build123d is much simpler than DeepCAD JSON to Build123d because both libraries use the same OpenCascade kernel and have well-documented API mappings.

## Revised Time-Optimal Plan

| Step | Time | What |
|---|---|---|
| Download GenCAD-Code (163K) | 15 min | `huggingface-cli download` |
| Download CADEvolve (1.3M) | 30 min | `huggingface-cli download` |
| Download ExeCAD (16.5K) | 10 min | Already has text pairs |
| Write CadQuery→Build123d-FTC transpiler | 2 hours | One script |
| Transpile + validate best 10-15K | 3 hours | Batch process |
| Generate templates (your existing pipeline) | 3 hours | Still valuable for diversity |
| Generate editing samples | 2 hours | Derived from above |
| Assembly + QC | 1 hour | Merge all sources |

**You could have 15,000-20,000 samples** instead of 8,500 because the hard work (DeepCAD→code conversion, text annotation) is already done.

## What To Tell Claude Code Right Now

Paste this into your running Claude Code session:

```
URGENT UPDATE: There are pre-built CadQuery datasets on HuggingFace that save us the entire DeepCAD conversion step. After you finish the current template generation, add this as the next phase:

1. Download: huggingface-cli download CADCODER/GenCAD-Code --repo-type=dataset --local-dir /scratch/raw/gencad_code
2. Download: huggingface-cli download kulibinai/cadevolve --repo-type=dataset --local-dir /scratch/raw/cadevolve
3. Build a CadQuery→Build123d-FTC transpiler that converts the CadQuery fluent API to our BuildPart context manager convention
4. Transpile the top 10K samples (filtered by code length 10-80 lines, must have .hole() or .fillet() or .chamfer() for interesting parts)
5. Generate text prompts for any samples missing them
6. Validate all transpiled samples with our FTC validator
7. Merge with template-generated samples

This replaces the DeepCAD conversion phase entirely. The CadQuery→Build123d conversion is much simpler than DeepCAD JSON→Build123d.
```

**Don't skip your template generation though** — those are still your highest-quality samples because you control every variable and prompt. The downloaded datasets add volume and diversity on top.
