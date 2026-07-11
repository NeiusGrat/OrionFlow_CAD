"""Generate-pillar eval cases: text -> FeatureGraph -> native feature tree.

Scored from the compiled graph (``expect_in_graph``), never from the model's
prose: the requested dimensions must actually land in the IR that FreeCAD
builds. Run with:  python -m orion_agent.evals.run generate
"""

from __future__ import annotations

from orion_agent.evals.harness import EvalCase
from orion_agent.evals.synthetic import SyntheticModel


def _blank() -> SyntheticModel:
    return SyntheticModel(name="Blank", tier="empty", faces=0, edges=0,
                          vertices=0, planar_faces=0, volume=0.0)


def cases() -> list[EvalCase]:
    return [
        EvalCase(
            name="plate_center_hole",
            pillar="generate",
            model=_blank(),
            prompt="Create a rectangular plate 80 x 50 x 10 mm with a single "
                   "10 mm diameter hole through the centre.",
            expect_tools=["create_featuregraph"],
            expect_in_graph=[10.0, 5.0],       # thickness + hole radius
        ),
        EvalCase(
            name="flange_8_bolts",
            pillar="generate",
            model=_blank(),
            prompt="Design a flange: 120 mm outer diameter, 30 mm centre bore, "
                   "10 mm thick, with 8 bolt holes of 8 mm diameter on a 90 mm "
                   "bolt circle.",
            expect_tools=["create_featuregraph"],
            expect_in_graph=[60.0, 15.0, 8.0, 45.0],   # radii, count, bolt-circle radius
        ),
        EvalCase(
            name="rounded_block",
            pillar="generate",
            model=_blank(),
            prompt="Make a 60 x 40 x 15 mm block with 5 mm rounded vertical "
                   "corners.",
            expect_tools=["create_featuregraph"],
            expect_in_graph=[15.0, 5.0],       # height + fillet radius
        ),
        EvalCase(
            name="stepped_shaft",
            pillar="generate",
            model=_blank(),
            prompt="Create a stepped shaft: 30 mm diameter for the first 20 mm, "
                   "then 20 mm diameter for the next 30 mm.",
            expect_tools=["create_featuregraph"],
            expect_in_graph=[15.0, 10.0],      # the two radii
        ),
        EvalCase(
            name="hole_row",
            pillar="generate",
            model=_blank(),
            prompt="A 100 x 40 x 8 mm bar with a row of five 6 mm holes spaced "
                   "20 mm apart along its length.",
            expect_tools=["create_featuregraph"],
            expect_in_graph=[8.0, 3.0, 5.0],   # thickness, hole radius, count
        ),
    ]
