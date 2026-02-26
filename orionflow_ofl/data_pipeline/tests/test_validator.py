"""Tests for OFL code validator."""

import pytest
from orionflow_ofl.data_pipeline.validator import OFLValidator


@pytest.fixture
def validator():
    return OFLValidator()


class TestValidCode:
    def test_simple_rect(self, validator):
        code = '''from orionflow_ofl import *
part = Sketch(Plane.XY).rect(50, 50).extrude(5)
export(part, "test.step")'''
        result = validator.validate(code)
        assert result["valid"] is True
        assert result["step_file_size"] > 100

    def test_with_hole(self, validator):
        code = '''from orionflow_ofl import *
part = Sketch(Plane.XY).rect(60, 60).extrude(5)
part -= Hole(10).at(0, 0).through().label("center")
export(part, "test.step")'''
        result = validator.validate(code)
        assert result["valid"] is True


class TestInvalidCode:
    def test_syntax_error(self, validator):
        code = "this is not python"
        result = validator.validate(code)
        assert result["valid"] is False
        assert result["error"] is not None

    def test_import_error(self, validator):
        code = "import nonexistent_module_xyz"
        result = validator.validate(code)
        assert result["valid"] is False

    def test_no_step_output(self, validator):
        code = "x = 1 + 1"
        result = validator.validate(code)
        assert result["valid"] is False
        assert "no STEP" in result["error"]


class TestTimeout:
    def test_long_running_code(self, validator):
        code = "import time; time.sleep(60)"
        result = validator.validate(code, timeout=2)
        assert result["valid"] is False
        assert "timeout" in result["error"].lower() if result["error"] else True
