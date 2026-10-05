"""The Claude vision path, end to end, with the API call stubbed (no network, no cost).

A scanned sheet has no text layer; with a Claude key configured the pipeline must
send it to the vision reader, parse what comes back with the same deterministic
parsers, mark those characteristics 'vision', and record model and cost.
"""
from __future__ import annotations

import pytest

import drawcheck.extract_vision as ev
from drawcheck.samples import make


def test_scanned_sheet_goes_through_claude(tmp_path, monkeypatch):
    pdf = make("scanned", tmp_path / "scanned.pdf")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.delenv("DRAWCHECK_VISION_MODEL", raising=False)
    monkeypatch.setattr(ev, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fake_call_claude(png, size, model, timeout=600.0):
        calls.append((model, size))
        w, h = size
        raw = {"annotations": [
            {"kind": "dimension", "text": "Ø30 +0.021/0", "box": [int(0.15 * w), int(0.40 * h), int(0.19 * w), int(0.42 * h)],
             "characteristic": "none", "tolerance": None, "basic": False, "diameter_zone": False,
             "material_modifier": "none", "datums": [], "field": "none", "projection": "none"},
            {"kind": "gdt_frame", "text": "⌖ Ø0.2 Ⓜ A B C", "box": [int(0.12 * w), int(0.56 * h), int(0.24 * w), int(0.58 * h)],
             "characteristic": "position", "tolerance": 0.2, "basic": False, "diameter_zone": True,
             "material_modifier": "MMC", "datums": ["A", "B", "C"], "field": "none", "projection": "none"},
            {"kind": "note", "text": "2. GENERAL TOLERANCES ISO 2768-mK", "box": [int(0.03 * w), int(0.69 * h), int(0.25 * w), int(0.70 * h)],
             "characteristic": "none", "tolerance": None, "basic": False, "diameter_zone": False,
             "material_modifier": "none", "datums": [], "field": "none", "projection": "none"},
        ]}
        return {"annotations": ev.claude_items(raw, size)}, {
            "model": model, "seconds": 1.0, "input_tokens": 3000, "output_tokens": 900, "cost_usd": 0.03, "cached": False}

    monkeypatch.setattr(ev, "call_claude", fake_call_claude)
    from fai.pipeline import run

    res = run(pdf, None, None, {}, tmp_path)
    assert calls and calls[0][0] == "claude-opus-5-5"
    assert 2400 < max(calls[0][1]) <= ev.CLAUDE_MAX_SIDE                 # rendered up to Claude's limit
    chars = res["characteristics"]
    bore = next(c for c in chars if c["designator"].startswith("Ø30"))
    assert (bore["lower"], bore["upper"], bore["confidence"]) == (30.0, 30.021, "vision")
    pos = next(c for c in chars if c["kind"] == "gdt")
    assert pos["type"] == "Position" and pos["upper"] == 0.2 and pos["confidence"] == "vision"
    assert res["stats"]["model"] == "claude-opus-5-5" and res["stats"]["cost_usd"] == pytest.approx(0.03)
    assert any("read by claude-opus-5-5" in w for w in res["warnings"])


def test_no_key_means_no_call(tmp_path, monkeypatch):
    pdf = make("scanned", tmp_path / "scanned.pdf")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DRAWCHECK_VISION_MODEL", raising=False)
    monkeypatch.setattr(ev, "call_claude", lambda *a, **k: pytest.fail("must not call a model without a key"))
    monkeypatch.setattr(ev, "call_gemini", lambda *a, **k: pytest.fail("must not fall back to another provider"))
    from fai.pipeline import run

    res = run(pdf, None, None, {}, tmp_path)
    assert res["stats"]["model"] == "none" and res["characteristics"] == []
    assert any("entered by hand" in w for w in res["warnings"])
