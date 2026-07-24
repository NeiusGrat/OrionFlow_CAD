"""OrionForge — blueprint-first verified CAD data generation.

The contract, in one sentence: a frozen mathematical Blueprint predicts every
measurable property of a part BEFORE FreeCAD builds it, and a record only
enters the corpus when the measured geometry agrees with the frozen prediction.

Two runtimes on purpose:
  * system Python  — blueprint math, static checking, closed-form prediction
    (`expr`, `blueprint`, `profiles`, `checker`, `tier1`)
  * FreeCAD Python — build + measurement only (`measure_fc`), invoked as a
    subprocess exactly like freecad/reconstruct.py

Nothing here imports `app.*` or `orion_agent.*`; the only repo coupling is the
FeatureGraph vocabulary shared with freecad/reconstruct.py.
"""

__version__ = "0.1.0"
