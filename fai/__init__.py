"""OrionFlow Inspect — first article inspection paperwork from a drawing (and its CAD).

Drawing PDF (+ STEP, + BOM/PO) in; ballooned characteristics, drawing-vs-CAD
cross-check, and an AS9102 Form 1/2/3 draft out, ready for a quality engineer
to review and sign.

Deterministic throughout: the drawing is read by ``drawcheck``'s text-layer
reader, tolerances come from ISO 2768 / ISO 286 tables, CAD values are measured
with OpenCASCADE, and every status is arithmetic on those numbers. A language
model may later *assist reading* (see :mod:`fai.assist`); it never decides a
status.

Isolated from ``app``: imports ``drawcheck`` and ``interface_check`` only.
"""
ENGINE_VERSION = "fai-1.0.0"
