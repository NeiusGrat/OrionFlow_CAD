"""Tests for few-shot examples validity."""

import pytest
from orionflow_ofl.baseline.few_shot_examples import FEW_SHOT_EXAMPLES
from orionflow_ofl.data_pipeline.validator import OFLValidator


@pytest.fixture(scope="module")
def validator():
    return OFLValidator()


class TestFewShotExamples:
    def test_five_examples(self):
        assert len(FEW_SHOT_EXAMPLES) == 5

    def test_all_have_text_and_code(self):
        for ex in FEW_SHOT_EXAMPLES:
            assert "text" in ex and len(ex["text"]) > 10
            assert "code" in ex and len(ex["code"]) > 20

    def test_all_have_import(self):
        for ex in FEW_SHOT_EXAMPLES:
            assert "from orionflow_ofl import *" in ex["code"]

    def test_all_have_export(self):
        for ex in FEW_SHOT_EXAMPLES:
            assert "export(" in ex["code"]

    @pytest.mark.parametrize("idx", range(5))
    def test_example_produces_valid_step(self, validator, idx):
        ex = FEW_SHOT_EXAMPLES[idx]
        result = validator.validate(ex["code"])
        assert result["valid"], (
            f"Few-shot example {idx} failed: "
            f"{ex['text'][:40]}... Error: {result.get('error')}"
        )
