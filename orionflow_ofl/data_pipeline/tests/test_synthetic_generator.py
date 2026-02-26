"""Tests for synthetic OFL training pair generator."""

import pytest
from orionflow_ofl.data_pipeline.synthetic_generator import SyntheticGenerator


@pytest.fixture
def gen():
    return SyntheticGenerator(seed=42)


class TestGenerateOne:
    def test_returns_text_and_code(self, gen):
        text, code = gen.generate_one()
        assert isinstance(text, str) and len(text) > 10
        assert isinstance(code, str)
        assert "from orionflow_ofl import *" in code
        assert "export(" in code

    def test_code_has_part(self, gen):
        _, code = gen.generate_one()
        assert "part" in code
        assert "Sketch(" in code


class TestAllTemplates:
    def test_all_templates_produce_output(self, gen):
        for name in gen.list_templates():
            text, code = gen.generate_from_template(name)
            assert code is not None, f"Template {name} produced None"
            assert "from orionflow_ofl import *" in code, f"Template {name} missing import"
            assert "export(" in code, f"Template {name} missing export"
            assert len(text) > 5, f"Template {name} text too short: {text!r}"

    def test_twenty_templates(self, gen):
        assert len(gen.list_templates()) == 20


class TestDimensionRanges:
    def test_no_negative_dimensions(self):
        gen = SyntheticGenerator(seed=123)
        for _ in range(200):
            _, code = gen.generate_one()
            # extract numeric assignments
            import re
            assignments = re.findall(r"^(\w+)\s*=\s*([\d.]+)", code, re.MULTILINE)
            for name, val in assignments:
                v = float(val)
                assert v >= 0, f"Negative dimension {name}={v} in generated code"

    def test_no_zero_thickness(self):
        gen = SyntheticGenerator(seed=456)
        for _ in range(200):
            _, code = gen.generate_one()
            import re
            m = re.search(r"(?:thickness|length)\s*=\s*([\d.]+)", code)
            if m:
                v = float(m.group(1))
                assert v > 0, f"Zero thickness/length in generated code"


class TestDescriptionLevels:
    def test_varied_detail_levels(self):
        gen = SyntheticGenerator(seed=789)
        texts = [gen.generate_one()[0] for _ in range(50)]
        has_numbers = sum(1 for t in texts if any(c.isdigit() for c in t))
        assert 5 < has_numbers < 48, f"Too uniform detail levels: {has_numbers}/50 have numbers"


class TestBatch:
    def test_batch_generation(self, gen):
        pairs = gen.generate_batch(20)
        assert len(pairs) == 20
        for p in pairs:
            assert "text" in p
            assert "code" in p
            assert "source" in p
            assert p["source"] == "synthetic"
            assert "complexity" in p
            assert 1 <= p["complexity"] <= 5
