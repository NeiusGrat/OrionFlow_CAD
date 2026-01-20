"""
Tests for FeatureGraphIR - Execution IR validation.

These tests ensure the IR contract is enforced:
1. All parameters must be resolved (no "$param" references)
2. Dependencies must form a valid DAG
3. Forbidden fields are rejected
4. Conversion from FeatureGraph works correctly
"""
import pytest
from app.domain.feature_graph_ir import (
    FeatureGraphIR,
    FeatureIR,
    SketchIR,
    SketchPrimitiveIR,
    SketchConstraintIR,
    ResolvedParameter,
    IRBuilder,
    FeatureType,
    PrimitiveType,
    ConstraintType,
    SketchPlane,
)
from app.domain.feature_graph import FeatureGraph, Feature, Sketch, SketchEntity


class TestResolvedParameter:
    """Tests for ResolvedParameter validation."""

    def test_valid_parameter(self):
        """Valid numeric parameter."""
        param = ResolvedParameter(value=10.0)
        assert param.value == 10.0

    def test_parameter_with_bounds(self):
        """Parameter with valid bounds."""
        param = ResolvedParameter(value=10.0, min_value=5.0, max_value=20.0)
        assert param.value == 10.0

    def test_parameter_below_minimum(self):
        """Parameter below minimum should fail."""
        with pytest.raises(ValueError, match="below minimum"):
            ResolvedParameter(value=3.0, min_value=5.0)

    def test_parameter_above_maximum(self):
        """Parameter above maximum should fail."""
        with pytest.raises(ValueError, match="above maximum"):
            ResolvedParameter(value=25.0, max_value=20.0)

    def test_nan_parameter(self):
        """NaN parameter should fail."""
        import math
        with pytest.raises(ValueError, match="must be finite"):
            ResolvedParameter(value=math.nan)

    def test_inf_parameter(self):
        """Infinite parameter should fail."""
        import math
        with pytest.raises(ValueError, match="must be finite"):
            ResolvedParameter(value=math.inf)


class TestSketchPrimitiveIR:
    """Tests for SketchPrimitiveIR validation."""

    def test_valid_primitive(self):
        """Valid primitive with resolved params."""
        prim = SketchPrimitiveIR(
            id="p1",
            type=PrimitiveType.RECTANGLE,
            params={"width": 10.0, "height": 20.0}
        )
        assert prim.params["width"] == 10.0

    def test_unresolved_param_fails(self):
        """String parameter reference should fail."""
        with pytest.raises(ValueError, match="IR violation"):
            SketchPrimitiveIR(
                id="p1",
                type=PrimitiveType.RECTANGLE,
                params={"width": "$width", "height": 20.0}
            )

    def test_int_params_converted_to_float(self):
        """Integer params should be converted to float."""
        prim = SketchPrimitiveIR(
            id="p1",
            type=PrimitiveType.CIRCLE,
            params={"radius": 10}
        )
        assert isinstance(prim.params["radius"], float)


class TestFeatureIR:
    """Tests for FeatureIR validation."""

    def test_valid_feature(self):
        """Valid feature with resolved params."""
        feat = FeatureIR(
            id="f1",
            type=FeatureType.EXTRUDE,
            sketch="s1",
            params={"depth": 25.0},
            depends_on=[]
        )
        assert feat.params["depth"] == 25.0

    def test_unresolved_feature_param_fails(self):
        """String parameter in feature should fail."""
        with pytest.raises(ValueError, match="IR violation"):
            FeatureIR(
                id="f1",
                type=FeatureType.EXTRUDE,
                params={"depth": "$height"}
            )

    def test_param_hash_computation(self):
        """Feature should compute deterministic param hash."""
        feat = FeatureIR(
            id="f1",
            type=FeatureType.EXTRUDE,
            params={"depth": 25.0}
        )
        hash1 = feat.compute_param_hash()
        hash2 = feat.compute_param_hash()
        assert hash1 == hash2
        assert len(hash1) == 16


class TestFeatureGraphIR:
    """Tests for FeatureGraphIR validation."""

    def test_valid_ir(self):
        """Valid IR with resolved everything."""
        ir = FeatureGraphIR(
            version="1.0-IR",
            units="mm",
            parameters={"height": ResolvedParameter(value=20.0)},
            sketches=[
                SketchIR(
                    id="s1",
                    plane=SketchPlane.XY,
                    primitives=[
                        SketchPrimitiveIR(
                            id="p1",
                            type=PrimitiveType.RECTANGLE,
                            params={"width": 10.0, "height": 10.0}
                        )
                    ]
                )
            ],
            features=[
                FeatureIR(
                    id="f1",
                    type=FeatureType.EXTRUDE,
                    sketch="s1",
                    params={"depth": 20.0}
                )
            ]
        )
        assert ir.version == "1.0-IR"
        assert ir.get_resolved_param("height") == 20.0

    def test_empty_features_fails(self):
        """IR must have at least one feature."""
        with pytest.raises(ValueError, match="at least one feature"):
            FeatureGraphIR(
                version="1.0-IR",
                parameters={},
                sketches=[],
                features=[]
            )

    def test_invalid_dependency_fails(self):
        """Feature depending on non-existent feature should fail."""
        with pytest.raises(ValueError, match="unknown feature"):
            FeatureGraphIR(
                version="1.0-IR",
                parameters={},
                sketches=[],
                features=[
                    FeatureIR(
                        id="f1",
                        type=FeatureType.FILLET,
                        params={"radius": 2.0},
                        depends_on=["nonexistent"]
                    )
                ]
            )

    def test_invalid_sketch_reference_fails(self):
        """Feature referencing non-existent sketch should fail."""
        with pytest.raises(ValueError, match="unknown sketch"):
            FeatureGraphIR(
                version="1.0-IR",
                parameters={},
                sketches=[],
                features=[
                    FeatureIR(
                        id="f1",
                        type=FeatureType.EXTRUDE,
                        sketch="nonexistent",
                        params={"depth": 10.0}
                    )
                ]
            )

    def test_dependency_cycle_fails(self):
        """Circular dependency should fail."""
        with pytest.raises(ValueError, match="cycle"):
            FeatureGraphIR(
                version="1.0-IR",
                parameters={},
                sketches=[],
                features=[
                    FeatureIR(
                        id="f1",
                        type=FeatureType.EXTRUDE,
                        params={"depth": 10.0},
                        depends_on=["f2"]
                    ),
                    FeatureIR(
                        id="f2",
                        type=FeatureType.FILLET,
                        params={"radius": 2.0},
                        depends_on=["f1"]
                    )
                ]
            )

    def test_topological_sort(self):
        """Features should be sorted by dependencies."""
        ir = FeatureGraphIR(
            version="1.0-IR",
            parameters={},
            sketches=[
                SketchIR(
                    id="s1",
                    plane=SketchPlane.XY,
                    primitives=[
                        SketchPrimitiveIR(
                            id="p1",
                            type=PrimitiveType.RECTANGLE,
                            params={"width": 10.0, "height": 10.0}
                        )
                    ]
                )
            ],
            features=[
                FeatureIR(
                    id="f2",
                    type=FeatureType.FILLET,
                    params={"radius": 2.0},
                    depends_on=["f1"]
                ),
                FeatureIR(
                    id="f1",
                    type=FeatureType.EXTRUDE,
                    sketch="s1",
                    params={"depth": 10.0},
                    depends_on=[]
                )
            ]
        )
        sorted_features = ir.topological_sort_features()
        assert sorted_features[0].id == "f1"
        assert sorted_features[1].id == "f2"

    def test_graph_hash_deterministic(self):
        """Graph hash should be deterministic."""
        ir = FeatureGraphIR(
            version="1.0-IR",
            parameters={"h": ResolvedParameter(value=20.0)},
            sketches=[],
            features=[
                FeatureIR(
                    id="f1",
                    type=FeatureType.EXTRUDE,
                    params={"depth": 20.0}
                )
            ]
        )
        hash1 = ir.compute_graph_hash()
        hash2 = ir.compute_graph_hash()
        assert hash1 == hash2


class TestIRBuilder:
    """Tests for IRBuilder - converting FeatureGraph to IR."""

    def test_resolve_param_value_float(self):
        """Direct float should resolve as-is."""
        result = IRBuilder.resolve_param_value(10.5, {})
        assert result == 10.5

    def test_resolve_param_value_int(self):
        """Int should resolve to float."""
        result = IRBuilder.resolve_param_value(10, {})
        assert result == 10.0

    def test_resolve_param_value_reference(self):
        """$param reference should resolve from table."""
        result = IRBuilder.resolve_param_value("$height", {"height": 25.0})
        assert result == 25.0

    def test_resolve_param_value_unknown_reference(self):
        """Unknown $param should fail."""
        with pytest.raises(ValueError, match="not in parameter table"):
            IRBuilder.resolve_param_value("$unknown", {"height": 25.0})

    def test_resolve_param_value_numeric_string(self):
        """Numeric string should parse."""
        result = IRBuilder.resolve_param_value("15.5", {})
        assert result == 15.5


class TestFeatureGraphIRConversion:
    """Tests for FeatureGraph -> IR conversion."""

    def test_validate_for_ir_clean(self):
        """Clean FeatureGraph should pass validation."""
        fg = FeatureGraph(
            version="v1",
            units="mm",
            parameters={"height": 20.0},
            sketches=[
                Sketch(
                    id="s1",
                    plane="XY",
                    entities=[
                        SketchEntity(
                            id="e1",
                            type="rectangle",
                            params={"width": 10.0, "height": "$height"}
                        )
                    ]
                )
            ],
            features=[
                Feature(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": "$height"}
                )
            ],
            metadata={"source": "test"}
        )
        violations = fg.validate_for_ir()
        assert len(violations) == 0

    def test_validate_for_ir_forbidden_metadata(self):
        """Forbidden metadata should be flagged."""
        fg = FeatureGraph(
            version="v1",
            units="mm",
            parameters={"height": 20.0},
            sketches=[],
            features=[
                Feature(
                    id="f1",
                    type="extrude",
                    params={"depth": 20.0}
                )
            ],
            metadata={
                "symmetry": True,
                "manufacturing_intent": "CNC"
            }
        )
        violations = fg.validate_for_ir()
        assert len(violations) == 2
        assert any("symmetry" in v for v in violations)
        assert any("manufacturing_intent" in v for v in violations)

    def test_validate_for_ir_undefined_reference(self):
        """Undefined parameter reference should be flagged."""
        fg = FeatureGraph(
            version="v1",
            units="mm",
            parameters={},  # height not defined
            sketches=[],
            features=[
                Feature(
                    id="f1",
                    type="extrude",
                    params={"depth": "$height"}
                )
            ]
        )
        violations = fg.validate_for_ir()
        assert len(violations) == 1
        assert "height" in violations[0]

    def test_strip_forbidden_fields(self):
        """Forbidden fields should be stripped."""
        fg = FeatureGraph(
            version="v1",
            units="mm",
            parameters={},
            sketches=[],
            features=[
                Feature(id="f1", type="extrude", params={"depth": 10.0})
            ],
            metadata={
                "source": "test",
                "symmetry": True,
                "design_rationale": "because"
            }
        )
        clean = fg.strip_forbidden_fields()
        assert "source" in clean.metadata
        assert "symmetry" not in clean.metadata
        assert "design_rationale" not in clean.metadata
