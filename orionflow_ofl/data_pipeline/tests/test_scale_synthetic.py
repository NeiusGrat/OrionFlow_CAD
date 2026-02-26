"""Tests for scale_synthetic and description_augmenter."""

import json
import os
import re
import tempfile

import pytest

from orionflow_ofl.data_pipeline.description_augmenter import DescriptionAugmenter
from orionflow_ofl.data_pipeline.quality_filter import QualityFilter
from orionflow_ofl.data_pipeline.scale_synthetic import ScaleSyntheticGenerator


class TestDescriptionAugmenter:
    def test_generates_varied_descriptions(self):
        aug = DescriptionAugmenter()
        texts = aug.augment(
            params={"width": 60, "height": 60, "thickness": 6},
            part_type="rect",
            num_variants=5,
        )
        assert len(texts) == 5
        assert len(set(texts)) >= 3  # at least 3 unique phrasings

    def test_circle_descriptions(self):
        aug = DescriptionAugmenter()
        texts = aug.augment(
            params={"diameter": 100, "thickness": 8, "bore": 50},
            part_type="circle",
            num_variants=5,
        )
        assert len(texts) == 5
        # should mention diameter somewhere
        assert any("100" in t for t in texts)

    def test_descriptions_with_holes(self):
        aug = DescriptionAugmenter()
        texts = aug.augment(
            params={
                "width": 80, "height": 80, "thickness": 6,
                "bolt_dia": 5.5, "bolt_count": 4, "pcd": 50,
            },
            part_type="rect",
            num_variants=5,
        )
        assert len(texts) == 5
        # at least some should mention holes/bolt pattern
        assert any("bolt" in t.lower() or "hole" in t.lower() or "M5" in t for t in texts)

    def test_no_empty_descriptions(self):
        aug = DescriptionAugmenter()
        for _ in range(50):
            texts = aug.augment(
                params={"width": 60, "height": 40, "thickness": 3},
                part_type="rect",
                num_variants=3,
            )
            for t in texts:
                assert len(t.strip()) > 5, f"Empty or too-short description: {t!r}"


class TestQualityFilter:
    def test_removes_exact_duplicates(self):
        pairs = [
            {"text": "a flat rectangular plate", "code": "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(50,50).extrude(5)\nexport(part,'p.step')", "complexity": 1},
            {"text": "a flat rectangular plate", "code": "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(50,50).extrude(5)\nexport(part,'p.step')", "complexity": 1},
        ]
        filtered = QualityFilter().filter(pairs)
        assert len(filtered) == 1

    def test_removes_bad_code(self):
        pairs = [
            {"text": "a good rectangular plate", "code": "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(50,50).extrude(5)\nexport(part,'p.step')", "complexity": 1},
            {"text": "bad code no import here", "code": "print('hello')", "complexity": 1},
            {"text": "bad code too short here", "code": "from orionflow_ofl import *\nexport(part,'x.step')", "complexity": 1},
        ]
        filtered = QualityFilter().filter(pairs)
        assert len(filtered) == 1
        assert filtered[0]["text"] == "a good rectangular plate"

    def test_removes_short_text(self):
        pairs = [
            {"text": "ok", "code": "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(50,50).extrude(5)\nexport(part,'p.step')", "complexity": 1},
        ]
        filtered = QualityFilter().filter(pairs)
        assert len(filtered) == 0  # "ok" is too short (< 3 words)

    def test_balance_complexity(self):
        pairs = []
        # 100 pairs at complexity 1, 10 at complexity 3
        for i in range(100):
            pairs.append({"text": f"plate {i}", "code": f"c{i}", "complexity": 1})
        for i in range(10):
            pairs.append({"text": f"flange {i}", "code": f"f{i}", "complexity": 3})

        balanced = QualityFilter().balance_complexity(pairs, max_per_complexity=50)
        c1_count = sum(1 for p in balanced if p["complexity"] == 1)
        c3_count = sum(1 for p in balanced if p["complexity"] == 3)
        # complexity 1 should be capped below 100
        assert c1_count < 100
        assert c3_count == 10  # all kept (below cap)

    def test_filter_returns_stats(self):
        pairs = [
            {"text": "a good rectangular plate here", "code": "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(50,50).extrude(5)\nexport(part,'p.step')", "complexity": 1},
        ]
        qf = QualityFilter()
        qf.filter(pairs)
        stats = qf.last_stats
        assert "kept" in stats
        assert stats["kept"] == 1


class TestScaleSyntheticGenerator:
    def test_small_batch(self):
        tmp = tempfile.mkdtemp(prefix="ofl_scale_")
        out = os.path.join(tmp, "test.jsonl")
        gen = ScaleSyntheticGenerator(seed=42)
        stats = gen.generate_batch(
            num_pairs=100,
            validate=False,
            output_path=out,
        )
        assert stats["final_count"] == 100
        assert os.path.exists(out)
        with open(out) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 100
        # check format
        for line in lines[:5]:
            pair = json.loads(line)
            assert "text" in pair
            assert "code" in pair
            assert "source" in pair
            assert pair["source"] == "synthetic"

    def test_complexity_distribution_balanced(self):
        tmp = tempfile.mkdtemp(prefix="ofl_scale_")
        out = os.path.join(tmp, "test.jsonl")
        gen = ScaleSyntheticGenerator(seed=99)
        stats = gen.generate_batch(
            num_pairs=500,
            validate=False,
            output_path=out,
        )
        dist = stats["complexity_distribution"]
        # should have at least 3 different complexity levels
        assert len(dist) >= 3

    def test_all_templates_represented(self):
        tmp = tempfile.mkdtemp(prefix="ofl_scale_")
        out = os.path.join(tmp, "test.jsonl")
        gen = ScaleSyntheticGenerator(seed=42)
        stats = gen.generate_batch(
            num_pairs=500,
            validate=False,
            output_path=out,
        )
        # all 20 templates should appear
        assert len(stats["template_distribution"]) == 20

    def test_report_saved(self):
        tmp = tempfile.mkdtemp(prefix="ofl_scale_")
        out = os.path.join(tmp, "test.jsonl")
        gen = ScaleSyntheticGenerator(seed=42)
        gen.generate_batch(num_pairs=50, validate=False, output_path=out)
        report_path = out.replace(".jsonl", "_report.json")
        assert os.path.exists(report_path)
        report = json.loads(open(report_path).read())
        assert "final_count" in report
