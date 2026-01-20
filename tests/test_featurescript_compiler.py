"""
Tests for FeatureScript Compiler (STEP 5).

Tests IR → FeatureScript portability:
1. Basic extrude compilation
2. Fillet/Chamfer compilation
3. Cut (subtraction) compilation
4. Revolve compilation
5. Full program generation
6. Validation checks
"""
import pytest
from app.cad.onshape.featurescript_compiler import (
    FeatureScriptCompiler,
    FSProgram,
    FSSketch,
    FSSketchEntity,
    FSOperation,
    FSOperationType,
    FSBooleanOperation,
    FSParameter,
    compile_ir_to_featurescript,
    validate_ir_portability
)
from app.domain.feature_graph_ir import (
    FeatureGraphIR,
    FeatureIR,
    SketchIR,
    SketchPrimitiveIR,
    ResolvedParameter,
    FeatureType,
    PrimitiveType,
    SketchPlane
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def simple_box_ir():
    """Create a simple box IR for testing."""
    return FeatureGraphIR(
        version="1.0-IR",
        units="mm",
        parameters={
            "width": ResolvedParameter(value=50.0),
            "height": ResolvedParameter(value=30.0),
            "depth": ResolvedParameter(value=20.0)
        },
        sketches=[
            SketchIR(
                id="sketch_base",
                plane=SketchPlane.XY,
                primitives=[
                    SketchPrimitiveIR(
                        id="rect1",
                        type=PrimitiveType.RECTANGLE,
                        params={"width": 50.0, "height": 30.0}
                    )
                ],
                constraints=[]
            )
        ],
        features=[
            FeatureIR(
                id="extrude_base",
                type=FeatureType.EXTRUDE,
                sketch="sketch_base",
                params={"depth": 20.0},
                depends_on=[]
            )
        ],
        metadata={"source": "test"}
    )


@pytest.fixture
def box_with_fillet_ir():
    """Create a box with fillet IR for testing."""
    return FeatureGraphIR(
        version="1.0-IR",
        units="mm",
        parameters={
            "width": ResolvedParameter(value=50.0),
            "height": ResolvedParameter(value=30.0),
            "depth": ResolvedParameter(value=20.0),
            "fillet_radius": ResolvedParameter(value=3.0)
        },
        sketches=[
            SketchIR(
                id="sketch_base",
                plane=SketchPlane.XY,
                primitives=[
                    SketchPrimitiveIR(
                        id="rect1",
                        type=PrimitiveType.RECTANGLE,
                        params={"width": 50.0, "height": 30.0}
                    )
                ],
                constraints=[]
            )
        ],
        features=[
            FeatureIR(
                id="extrude_base",
                type=FeatureType.EXTRUDE,
                sketch="sketch_base",
                params={"depth": 20.0},
                depends_on=[]
            ),
            FeatureIR(
                id="fillet_edges",
                type=FeatureType.FILLET,
                sketch=None,
                params={"radius": 3.0},
                depends_on=["extrude_base"]
            )
        ],
        metadata={"source": "test"}
    )


@pytest.fixture
def cylinder_ir():
    """Create a cylinder IR for testing."""
    return FeatureGraphIR(
        version="1.0-IR",
        units="mm",
        parameters={
            "radius": ResolvedParameter(value=10.0),
            "height": ResolvedParameter(value=25.0)
        },
        sketches=[
            SketchIR(
                id="sketch_circle",
                plane=SketchPlane.XY,
                primitives=[
                    SketchPrimitiveIR(
                        id="circle1",
                        type=PrimitiveType.CIRCLE,
                        params={"radius": 10.0}
                    )
                ],
                constraints=[]
            )
        ],
        features=[
            FeatureIR(
                id="extrude_cylinder",
                type=FeatureType.EXTRUDE,
                sketch="sketch_circle",
                params={"depth": 25.0},
                depends_on=[]
            )
        ],
        metadata={"source": "test"}
    )


@pytest.fixture
def box_with_cut_ir():
    """Create a box with cut (hole) IR for testing."""
    return FeatureGraphIR(
        version="1.0-IR",
        units="mm",
        parameters={
            "width": ResolvedParameter(value=50.0),
            "height": ResolvedParameter(value=30.0),
            "depth": ResolvedParameter(value=20.0),
            "hole_radius": ResolvedParameter(value=5.0)
        },
        sketches=[
            SketchIR(
                id="sketch_base",
                plane=SketchPlane.XY,
                primitives=[
                    SketchPrimitiveIR(
                        id="rect1",
                        type=PrimitiveType.RECTANGLE,
                        params={"width": 50.0, "height": 30.0}
                    )
                ],
                constraints=[]
            ),
            SketchIR(
                id="sketch_hole",
                plane=SketchPlane.XY,
                primitives=[
                    SketchPrimitiveIR(
                        id="circle_hole",
                        type=PrimitiveType.CIRCLE,
                        params={"radius": 5.0}
                    )
                ],
                constraints=[]
            )
        ],
        features=[
            FeatureIR(
                id="extrude_base",
                type=FeatureType.EXTRUDE,
                sketch="sketch_base",
                params={"depth": 20.0},
                depends_on=[]
            ),
            FeatureIR(
                id="cut_hole",
                type=FeatureType.CUT,
                sketch="sketch_hole",
                params={"depth": 20.0},
                depends_on=["extrude_base"]
            )
        ],
        metadata={"source": "test"}
    )


# =============================================================================
# Test FeatureScript Compiler
# =============================================================================

class TestFeatureScriptCompiler:
    """Tests for FeatureScriptCompiler."""

    def test_compile_simple_box(self, simple_box_ir):
        """Compile simple box IR to FeatureScript."""
        compiler = FeatureScriptCompiler()
        fs_code = compiler.compile(simple_box_ir, "SimpleBox")

        # Check that output contains expected FeatureScript elements
        assert "FeatureScript 2240" in fs_code
        assert "import(path" in fs_code
        assert "defineFeature" in fs_code
        assert "opExtrude" in fs_code
        assert "SimpleBox" in fs_code

    def test_compile_box_with_fillet(self, box_with_fillet_ir):
        """Compile box with fillet to FeatureScript."""
        compiler = FeatureScriptCompiler()
        fs_code = compiler.compile(box_with_fillet_ir, "BoxWithFillet")

        assert "opExtrude" in fs_code
        assert "opFillet" in fs_code
        assert "3" in fs_code  # Fillet radius

    def test_compile_cylinder(self, cylinder_ir):
        """Compile cylinder to FeatureScript."""
        compiler = FeatureScriptCompiler()
        fs_code = compiler.compile(cylinder_ir, "Cylinder")

        assert "skCircle" in fs_code
        assert "10" in fs_code  # Radius

    def test_compile_cut_operation(self, box_with_cut_ir):
        """Compile cut operation correctly."""
        compiler = FeatureScriptCompiler()
        fs_code = compiler.compile(box_with_cut_ir, "BoxWithHole")

        # Cut should use BooleanOperationType.SUBTRACTION
        assert "BooleanOperationType.SUBTRACTION" in fs_code

    def test_compile_to_dict(self, simple_box_ir):
        """Compile IR to dictionary for API."""
        compiler = FeatureScriptCompiler()
        result = compiler.compile_to_dict(simple_box_ir)

        assert "parameters" in result
        assert "sketches" in result
        assert "operations" in result
        assert result["parameters"]["width"]["value"] == 50.0
        assert len(result["sketches"]) == 1
        assert len(result["operations"]) == 1

    def test_validation_passes_for_valid_ir(self, simple_box_ir):
        """Valid IR should pass validation."""
        compiler = FeatureScriptCompiler()
        errors = compiler.validate_ir_for_featurescript(simple_box_ir)
        assert len(errors) == 0

    def test_validation_detects_missing_sketch_reference(self):
        """Should detect missing sketch reference at IR construction."""
        # FeatureGraphIR validates sketch references during construction,
        # so we expect a Pydantic validation error
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            FeatureGraphIR(
                version="1.0-IR",
                units="mm",
                parameters={},
                sketches=[],
                features=[
                    FeatureIR(
                        id="extrude1",
                        type=FeatureType.EXTRUDE,
                        sketch="nonexistent_sketch",
                        params={"depth": 10.0},
                        depends_on=[]
                    )
                ],
                metadata={}
            )

        # Verify the error message
        assert "unknown sketch" in str(exc_info.value)


# =============================================================================
# Test FeatureScript AST Components
# =============================================================================

class TestFSParameter:
    """Tests for FSParameter."""

    def test_to_fs_millimeter(self):
        """Generate FeatureScript parameter in mm."""
        param = FSParameter(name="width", value=50.0, unit="millimeter")
        fs = param.to_fs()
        assert "width" in fs
        assert "50.0" in fs
        assert "millimeter" in fs


class TestFSSketchEntity:
    """Tests for FSSketchEntity."""

    def test_rectangle_to_fs(self):
        """Generate rectangle FeatureScript."""
        entity = FSSketchEntity(
            entity_id="rect1",
            entity_type="rectangle",
            params={"width": 50.0, "height": 30.0}
        )
        fs = entity.to_fs()
        assert "skRectangle" in fs
        assert "50" in fs
        assert "30" in fs

    def test_circle_to_fs(self):
        """Generate circle FeatureScript."""
        entity = FSSketchEntity(
            entity_id="circle1",
            entity_type="circle",
            params={"radius": 10.0}
        )
        fs = entity.to_fs()
        assert "skCircle" in fs
        assert "10" in fs

    def test_line_to_fs(self):
        """Generate line FeatureScript."""
        entity = FSSketchEntity(
            entity_id="line1",
            entity_type="line",
            params={"x1": 0, "y1": 0, "x2": 10, "y2": 10}
        )
        fs = entity.to_fs()
        assert "skLineSegment" in fs


class TestFSOperation:
    """Tests for FSOperation."""

    def test_extrude_to_fs(self):
        """Generate extrude FeatureScript."""
        op = FSOperation(
            operation_id="extrude1",
            operation_type=FSOperationType.OP_EXTRUDE,
            params={"depth": 20.0},
            sketch_ref="sketch1",
            boolean_op=FSBooleanOperation.NEW
        )
        fs = op.to_fs()
        assert "opExtrude" in fs
        assert "20" in fs
        assert "BooleanOperationType.NEW" in fs

    def test_fillet_to_fs(self):
        """Generate fillet FeatureScript."""
        op = FSOperation(
            operation_id="fillet1",
            operation_type=FSOperationType.OP_FILLET,
            params={"radius": 3.0, "target": "extrude1"}
        )
        fs = op.to_fs()
        assert "opFillet" in fs
        assert "3" in fs

    def test_chamfer_to_fs(self):
        """Generate chamfer FeatureScript."""
        op = FSOperation(
            operation_id="chamfer1",
            operation_type=FSOperationType.OP_CHAMFER,
            params={"distance": 2.0, "target": "extrude1"}
        )
        fs = op.to_fs()
        assert "opChamfer" in fs
        assert "2" in fs


class TestFSProgram:
    """Tests for FSProgram."""

    def test_full_program_generation(self):
        """Generate complete FeatureScript program."""
        program = FSProgram(
            feature_name="TestFeature",
            parameters=[
                FSParameter("width", 50.0),
                FSParameter("height", 30.0)
            ],
            sketches=[
                FSSketch(
                    sketch_id="sketch1",
                    plane="XY",
                    entities=[
                        FSSketchEntity("rect1", "rectangle", {"width": 50.0, "height": 30.0})
                    ]
                )
            ],
            operations=[
                FSOperation(
                    operation_id="extrude1",
                    operation_type=FSOperationType.OP_EXTRUDE,
                    params={"depth": 10.0},
                    sketch_ref="sketch1"
                )
            ]
        )

        fs = program.to_fs()

        # Check structure
        assert "FeatureScript 2240" in fs
        assert "import(path" in fs
        assert "defineFeature" in fs
        assert "precondition" in fs
        assert "TestFeature" in fs
        assert "newSketchOnPlane" in fs
        assert "skSolve" in fs
        assert "opExtrude" in fs


# =============================================================================
# Test Utility Functions
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_compile_ir_to_featurescript(self, simple_box_ir):
        """Convenience function should work."""
        fs_code = compile_ir_to_featurescript(simple_box_ir, "TestBox")
        assert "FeatureScript" in fs_code
        assert "TestBox" in fs_code

    def test_validate_ir_portability_valid(self, simple_box_ir):
        """Valid IR should be portable."""
        report = validate_ir_portability(simple_box_ir)
        assert report["is_portable"] is True
        assert len(report["errors"]) == 0
        assert "extrude_base" in report["supported_features"]

    def test_validate_ir_portability_with_unsupported(self):
        """IR with unsupported features should report them."""
        ir = FeatureGraphIR(
            version="1.0-IR",
            units="mm",
            parameters={},
            sketches=[
                SketchIR(
                    id="s1",
                    plane=SketchPlane.XY,
                    primitives=[
                        SketchPrimitiveIR(id="r1", type=PrimitiveType.RECTANGLE, params={"width": 10, "height": 10})
                    ]
                )
            ],
            features=[
                FeatureIR(
                    id="loft1",
                    type=FeatureType.LOFT,
                    params={"sections": 2.0},
                    depends_on=[]
                )
            ],
            metadata={}
        )

        report = validate_ir_portability(ir)
        # LOFT should be in unsupported (stub doesn't fully support it)
        assert "loft1" in report["unsupported_features"]


# =============================================================================
# Test Round-Trip Validation
# =============================================================================

class TestRoundTripValidation:
    """Tests that prove IR → FeatureScript portability."""

    def test_all_supported_feature_types_compile(self):
        """All supported feature types should compile."""
        supported_types = [
            FeatureType.EXTRUDE,
            FeatureType.FILLET,
            FeatureType.CHAMFER,
            FeatureType.REVOLVE,
            FeatureType.CUT
        ]

        for ftype in supported_types:
            ir = FeatureGraphIR(
                version="1.0-IR",
                units="mm",
                parameters={},
                sketches=[
                    SketchIR(
                        id="s1",
                        plane=SketchPlane.XY,
                        primitives=[
                            SketchPrimitiveIR(
                                id="r1",
                                type=PrimitiveType.RECTANGLE,
                                params={"width": 10, "height": 10}
                            )
                        ]
                    )
                ],
                features=[
                    FeatureIR(
                        id="f1",
                        type=ftype,
                        sketch="s1" if ftype in (FeatureType.EXTRUDE, FeatureType.CUT, FeatureType.REVOLVE) else None,
                        params={"depth": 10.0} if ftype in (FeatureType.EXTRUDE, FeatureType.CUT) else
                               {"radius": 2.0} if ftype == FeatureType.FILLET else
                               {"distance": 1.0} if ftype == FeatureType.CHAMFER else
                               {"angle": 360.0},
                        depends_on=[]
                    )
                ],
                metadata={}
            )

            compiler = FeatureScriptCompiler()
            fs_code = compiler.compile(ir, f"Test_{ftype}")

            # Should generate valid FeatureScript
            assert "FeatureScript" in fs_code, f"Failed for {ftype}"
            assert "defineFeature" in fs_code, f"Failed for {ftype}"

    def test_all_primitive_types_compile(self):
        """All primitive types should compile to sketch entities."""
        primitives = [
            (PrimitiveType.RECTANGLE, {"width": 10, "height": 10}),
            (PrimitiveType.CIRCLE, {"radius": 5}),
            (PrimitiveType.LINE, {"x1": 0, "y1": 0, "x2": 10, "y2": 10}),
            (PrimitiveType.ARC, {"x1": 0, "y1": 0, "xm": 5, "ym": 5, "x2": 10, "y2": 0}),
        ]

        for ptype, params in primitives:
            ir = FeatureGraphIR(
                version="1.0-IR",
                units="mm",
                parameters={},
                sketches=[
                    SketchIR(
                        id="s1",
                        plane=SketchPlane.XY,
                        primitives=[
                            SketchPrimitiveIR(id="p1", type=ptype, params=params)
                        ]
                    )
                ],
                features=[
                    FeatureIR(
                        id="f1",
                        type=FeatureType.EXTRUDE,
                        sketch="s1",
                        params={"depth": 10.0},
                        depends_on=[]
                    )
                ],
                metadata={}
            )

            compiler = FeatureScriptCompiler()
            fs_code = compiler.compile(ir)

            # Should include sketch geometry
            assert "sketch" in fs_code.lower(), f"Failed for {ptype}"
