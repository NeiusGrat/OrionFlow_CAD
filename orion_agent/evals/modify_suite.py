"""Modify-pillar eval cases (Tier B parametric edits).

These double as the GRPO reward environment: each case scores whether the edit
applied, survived recompute, and matched the stated numeric intent — all
verifiable from the synthetic model, no gold answer required.
"""

from __future__ import annotations

from orion_agent.evals.harness import EvalCase
from orion_agent.evals.synthetic import SyntheticModel


def cases() -> list[EvalCase]:
    plate = SyntheticModel(
        name="Plate", tier="B", faces=12, edges=30, vertices=20, planar_faces=10,
        holes=2, bbox=(60.0, 40.0, 3.0), volume=7000.0, hole_spacing=30.0,
        parameters={"Thickness": 3.0, "Length": 60.0, "Width": 40.0},
    )
    bar = SyntheticModel(
        name="Bar", tier="B", faces=6, edges=12, vertices=8, planar_faces=6,
        bbox=(100.0, 20.0, 10.0), volume=20000.0,
        parameters={"Length": 100.0, "Height": 10.0},
    )
    return [
        EvalCase("wall_thickness_4mm", "modify", plate,
                 "Increase the wall thickness to 4 mm.",
                 expect_tools=["set_parameter"], expect_param=("Thickness", 4.0)),
        EvalCase("length_to_80", "modify", bar,
                 "Change the length to 80 mm.",
                 expect_tools=["set_parameter"], expect_param=("Length", 80.0)),
        EvalCase("height_to_15", "modify", bar,
                 "Make the height 15 mm.",
                 expect_tools=["set_parameter"], expect_param=("Height", 15.0)),
    ]
