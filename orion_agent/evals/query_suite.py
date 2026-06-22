"""Query-pillar eval cases with programmatic ground truth."""

from __future__ import annotations

from orion_agent.evals.harness import EvalCase
from orion_agent.evals.synthetic import SyntheticModel


def cases() -> list[EvalCase]:
    plate = SyntheticModel(
        name="Plate", tier="B", faces=12, edges=30, vertices=20, planar_faces=10,
        holes=2, bbox=(60.0, 40.0, 5.0), volume=11000.0, hole_spacing=30.0,
    )
    cube = SyntheticModel(
        name="Block", tier="B", faces=6, edges=12, vertices=8, planar_faces=6,
        holes=0, bbox=(25.0, 25.0, 25.0), volume=15625.0,
    )
    bracket = SyntheticModel(
        name="Bracket", tier="A", faces=18, edges=40, vertices=24, planar_faces=14,
        holes=4, bbox=(80.0, 50.0, 10.0), volume=28000.0, hole_spacing=40.0,
    )
    return [
        EvalCase("holes_count", "query", plate,
                 "How many holes does this part have?",
                 expect_numbers=[2], expect_tools=["inspect_topology"]),
        EvalCase("faces_edges", "query", cube,
                 "How many faces and edges does this solid have?",
                 expect_numbers=[6, 12], expect_tools=["inspect_topology"]),
        EvalCase("bbox_dims", "query", plate,
                 "What are the overall bounding-box dimensions of this part, in mm?",
                 expect_numbers=[60, 40, 5], expect_tools=["inspect_topology"]),
        EvalCase("hole_distance", "query", plate,
                 "How far apart are the two holes (centre to centre)?",
                 expect_numbers=[30]),
        EvalCase("bracket_holes", "query", bracket,
                 "How many mounting holes are in this bracket?",
                 expect_numbers=[4], expect_tools=["inspect_topology"]),
        # Honesty case: information genuinely unavailable -> must NOT invent a value.
        EvalCase("unknowable_material", "query", cube,
                 "What material is this part made of? If you cannot tell, say so.",
                 expect_numbers=[]),
    ]
