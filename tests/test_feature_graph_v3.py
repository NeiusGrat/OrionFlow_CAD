"""Tests for FeatureGraph V3 (design-intent IR).

Covers:
- Basic schema creation
- Parameter-level constraint application
- Feature dependency topological sorting
- Round-trip conversion V1 -> V3 -> V1
"""
from app.domain.feature_graph_v1 import FeatureGraphV1
from app.domain.feature_graph_v3 import (
    FeatureGraphV3,
    Constraint,
    ConstraintType,
)
from app.domain.feature_graph_v2 import (
    SketchGraphV2,
    SketchPrimitiveV2,
    SketchConstraintV2,
    FeatureV2,
)


class TestFeatureGraphV3Schema:
    def test_basic_v3_schema(self):
        """V3 graph can be constructed with parameters, sketches, features, and constraints."""

        graph = FeatureGraphV3(
            units="mm",
            metadata={"intent": "Test box"},
            parameters={
                "width": {"type": "float", "value": 30.0},
                "height": {"type": "float", "value": 10.0},
            },
            sketches=[
                SketchGraphV2(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="p1",
                            type="rectangle",
                            params={"width": "$width", "height": "$height"},
                        )
                    ],
                    constraints=[
                        SketchConstraintV2(
                            type="horizontal",
                            entities=["p1.top"],
                        )
                    ],
                )
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": 5.0},
                    dependencies=[],
                )
            ],
            constraints=[
                Constraint(
                    id="c_equal",
                    type=ConstraintType.EQUAL,
                    parameters=["width", "height"],
                )
            ],
        )

        assert graph.version == "3.0"
        assert len(graph.sketches) == 1
        assert len(graph.features) == 1
        assert len(graph.constraints) == 1


class TestV3ParameterConstraints:
    def test_equal_constraint_unifies_parameters(self):
        """EQUAL constraints propagate the base parameter value to others."""

        g = FeatureGraphV3(
            parameters={
                "hole_d1": {"type": "float", "value": 10.0},
                "hole_d2": {"type": "float", "value": 5.0},
            },
            constraints=[
                Constraint(
                    id="c1",
                    type=ConstraintType.EQUAL,
                    parameters=["hole_d1", "hole_d2"],
                )
            ],
        )

        g.apply_parameter_constraints()

        assert g.parameters["hole_d1"]["value"] == 10.0
        assert g.parameters["hole_d2"]["value"] == 10.0

    def test_dimension_constraint_sets_value(self):
        """DIMENSION constraints set parameter values when numeric."""

        g = FeatureGraphV3(
            parameters={
                "height": {"type": "float", "value": 5.0},
            },
            constraints=[
                Constraint(
                    id="c2",
                    type=ConstraintType.DIMENSION,
                    parameters=["height"],
                    value=20.0,
                )
            ],
        )

        g.apply_parameter_constraints()

        assert g.parameters["height"]["value"] == 20.0


class TestV3FeatureDependencies:
    def test_topological_sort_respects_dependencies(self):
        """Features are ordered according to their dependency graph."""

        f1 = FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10}, dependencies=[])
        f2 = FeatureV2(id="f2", type="fillet", params={"radius": 2}, dependencies=["f1"])
        f3 = FeatureV2(id="f3", type="chamfer", params={"distance": 1}, dependencies=["f2"])

        g = FeatureGraphV3(features=[f2, f3, f1])  # Intentionally shuffled

        ordered = g.topologically_sorted_features()
        ordered_ids = [f.id for f in ordered]

        assert ordered_ids == ["f1", "f2", "f3"]


class TestV1V3RoundTrip:
    def test_round_trip_preserves_basic_structure(self):
        """FeatureGraphV1 -> V3 -> V1 round-trip keeps core information."""

        v1 = FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "round_trip"},
            parameters={
                "w": {"type": "float", "value": 10},
                "h": {"type": "float", "value": 20},
            },
            sketches=[
                {
                    "id": "s1",
                    "plane": "XY",
                    "primitives": [
                        {
                            "id": "p1",
                            "type": "rectangle",
                            "params": {"width": "w", "height": "h"},
                        }
                    ],
                    "constraints": [],
                }
            ],
            features=[
                {
                    "id": "f1",
                    "type": "extrude",
                    "sketch": "s1",
                    "params": {"depth": 5},
                }
            ],
        )

        v3 = FeatureGraphV3.from_v1(v1)
        v1_round = v3.to_v1()

        assert v1_round.schema_version == "1.0"
        assert v1_round.units == "mm"
        assert set(v1_round.parameters.keys()) == {"w", "h"}
        assert len(v1_round.sketches) == 1
        assert len(v1_round.features) == 1
        assert v1_round.features[0].type == "extrude"
