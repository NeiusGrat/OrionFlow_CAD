"""Tests for dataset builder orchestrator."""

import json
import os
import tempfile

import pytest
from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder


@pytest.fixture
def tmp_out():
    d = tempfile.mkdtemp(prefix="ofl_ds_test_")
    yield d
    # cleanup
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestBuildFromExamples:
    def test_produces_pairs(self, tmp_out):
        builder = DatasetBuilder(output_dir=tmp_out)
        path = builder.build_from_examples()
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        # at least 1 pair per example (50 examples × 5 texts = 250 ideally)
        assert len(lines) >= 50
        for line in lines:
            pair = json.loads(line)
            assert "text" in pair
            assert "code" in pair
            assert "source" in pair
            assert pair["source"] == "example"
            assert "complexity" in pair

    def test_code_has_required_structure(self, tmp_out):
        builder = DatasetBuilder(output_dir=tmp_out)
        path = builder.build_from_examples()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                pair = json.loads(line)
                code = pair["code"]
                assert "from orionflow_ofl import *" in code
                assert "export(" in code


class TestBuildSynthetic:
    def test_generate_small_batch(self, tmp_out):
        builder = DatasetBuilder(output_dir=tmp_out)
        path = builder.build_synthetic(num_samples=20)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 20


class TestMerge:
    def test_merge_and_dedup(self, tmp_out):
        builder = DatasetBuilder(output_dir=tmp_out)
        # create two files with overlap
        f1 = os.path.join(tmp_out, "a.jsonl")
        f2 = os.path.join(tmp_out, "b.jsonl")
        with open(f1, "w") as f:
            f.write(json.dumps({"text": "t1", "code": "c1", "source": "a", "complexity": 1}) + "\n")
            f.write(json.dumps({"text": "t2", "code": "c2", "source": "a", "complexity": 1}) + "\n")
        with open(f2, "w") as f:
            f.write(json.dumps({"text": "t1", "code": "c1", "source": "b", "complexity": 1}) + "\n")  # exact dup
            f.write(json.dumps({"text": "t3", "code": "c3", "source": "b", "complexity": 1}) + "\n")

        out = os.path.join(tmp_out, "merged.jsonl")
        stats = builder.merge_and_deduplicate([f1, f2], out)
        assert stats["total_pairs"] == 3  # exact text+code dup removed
        assert os.path.exists(out)


class TestBuildFromDeepCAD:
    def test_with_mock_json(self, tmp_out):
        # create a small DeepCAD-like directory
        dc_dir = os.path.join(tmp_out, "deepcad")
        os.makedirs(dc_dir)
        sample = {
            "sequence": [
                {
                    "type": "sketch",
                    "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": 1},
                    "loops": [{
                        "curves": [
                            {"type": "line", "start": [-0.5, -0.5], "end": [0.5, -0.5]},
                            {"type": "line", "start": [0.5, -0.5], "end": [0.5, 0.5]},
                            {"type": "line", "start": [0.5, 0.5], "end": [-0.5, 0.5]},
                            {"type": "line", "start": [-0.5, 0.5], "end": [-0.5, -0.5]},
                        ]
                    }],
                },
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        with open(os.path.join(dc_dir, "part001.json"), "w") as f:
            json.dump(sample, f)

        builder = DatasetBuilder(output_dir=tmp_out)
        path = builder.build_from_deepcad(dc_dir)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) >= 1
