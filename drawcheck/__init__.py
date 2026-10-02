"""drawcheck: check an incoming engineering drawing before you quote or machine it.

Reads a PDF drawing (the text layer exactly; scans through a vision model),
runs deterministic rules for title block, general tolerances, projection,
units, fits, threads, surface finish and GD&T, and writes the findings as an
annotated PDF and a technical query list to send back to the customer.

    python -m drawcheck check drawing.pdf --out reports/
    python -m drawcheck stackup "+50 ±0.1" "-49.8 ±0.05" --min 0
    python -m drawcheck serve

Standalone: it imports nothing from the rest of this repository.
"""
from .check import check_file, read
from .model import Annotation, Drawing, Finding, Report

__all__ = ["check_file", "read", "Annotation", "Drawing", "Finding", "Report"]
