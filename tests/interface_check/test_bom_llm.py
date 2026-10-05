"""BOM parsing and matching, the LLM guard, and the provider client."""
import json

import numpy as np
import pytest

from interface_check import llm as llm_mod
from interface_check.bom import norm, norm_loose, parse_bom, reconcile
from interface_check.components.datasheet import guard
from interface_check.models import Instance, Part


def _cad(spec: dict[str, int]):
    parts, instances = {}, []
    for k, (name, n) in enumerate(spec.items()):
        pid = f"p{k}"
        parts[pid] = Part(pid, name, None)
        for j in range(n):
            instances.append(Instance(f"i{len(instances)}", pid, f"robot/{name}#{j}", None, np.eye(4)))
    return parts, instances


def test_parse_bom_header_variants():
    rows = parse_bom("Item Number;Description;QTY.;Rev\nA-1;Base Plate;2;B\nA-2;Arm;1;\n")
    assert [(r.part_number, r.name, r.quantity, r.revision) for r in rows] == [
        ("A-1", "Base Plate", 2.0, "B"), ("A-2", "Arm", 1.0, "")]


def test_norm_keeps_designations():
    assert norm("608ZZ.step") == "608zz"
    assert norm_loose("bracket_2") == "bracket"
    assert norm_loose("NEMA-17") == "nema17"


def test_exact_fuzzy_and_quantities():
    parts, inst = _cad({"chassis_plate": 1, "side_bracket": 2, "standoff_M3x35": 4})
    rows = parse_bom("name,qty\nChasis Plate,1\nside-brackett,2\nstandoff_M3x35,3\nM3 screw,8\n")
    res = reconcile(rows, parts, inst)
    assert res.how == {0: "fuzzy", 1: "fuzzy", 2: "exact"}
    rules = sorted((f.rule_id, f.severity) for f in res.findings)
    assert rules == [("BOM_QTY_MISMATCH", "high"), ("IN_BOM_NOT_CAD", "low")]


def test_llm_cannot_invent_rows_or_parts():
    parts, inst = _cad({"shoulder_bracket_v3": 1, "upper_cover": 1})
    rows = parse_bom("part_number,name,qty\nSB-102,SHLDR BRKT,1\nUC-104,top lid,1\n")

    def fake(rows_sent, cad_names):
        assert {r.index for r in rows_sent} == {0, 1}
        return [(0, "shoulder_bracket_v3", 0.95),      # good
                (7, "upper_cover", 0.99),              # row it was never sent
                (1, "lower_cover", 0.99)]              # part that does not exist

    res = reconcile(rows, parts, inst, fake)
    assert res.pairs == {0: "p0"}
    assert {f.rule_id for f in res.findings} == {"IN_CAD_NOT_BOM", "IN_BOM_NOT_CAD"}


def test_llm_low_confidence_is_asked_not_used():
    parts, inst = _cad({"upper_cover": 1})
    rows = parse_bom("name,qty\ntop lid,1\n")
    res = reconcile(rows, parts, inst, lambda r, c: [(0, "upper_cover", 0.6)])
    assert res.pairs == {}
    assert "LOW_CONFIDENCE_MATCH" in {f.rule_id for f in res.findings}


def test_no_llm_degrades():
    with pytest.raises(llm_mod.LLMUnavailable):
        llm_mod.NoLLM().json("match_bom", "x", {})


def test_from_env(monkeypatch):
    for k in ("INTERFACE_CHECK_LLM_URL", "INTERFACE_CHECK_LLM_KEY", "INTERFACE_CHECK_LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(llm_mod.from_env(), llm_mod.NoLLM)
    monkeypatch.setenv("INTERFACE_CHECK_LLM_URL", "https://example.invalid/v1")
    monkeypatch.setenv("INTERFACE_CHECK_LLM_KEY", "k")
    monkeypatch.setenv("INTERFACE_CHECK_LLM_MODEL", "big")
    monkeypatch.setenv("INTERFACE_CHECK_LLM_MODEL_MATCH", "small")
    c = llm_mod.from_env()
    assert c.model_for("match_bom") == "small" and c.model_for("read_datasheet") == "big"


def test_chat_completions_request_and_cache(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr(llm_mod, "CACHE_DIR", tmp_path)
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"matches": [
                {"bom_row": 0, "cad_name": "arm", "confidence": 0.9}]})}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30}}

    def post(url, json, timeout, headers):
        calls.append((url, json, headers))
        return R()

    monkeypatch.setattr(httpx, "post", post)
    c = llm_mod.ChatCompletionsLLM("https://x/v1/", "secret", "m1")
    rows = parse_bom("name,qty\nARM LNK,1\n")
    assert llm_mod.match_bom(c, rows, ["arm"]) == [(0, "arm", 0.9)]
    assert llm_mod.match_bom(c, rows, ["arm"]) == [(0, "arm", 0.9)]       # second time from cache
    assert len(calls) == 1
    url, body, headers = calls[0]
    assert url == "https://x/v1/chat/completions" and headers["Authorization"] == "Bearer secret"
    assert body["temperature"] == 0 and body["response_format"]["json_schema"]["strict"] is True
    assert c.usage.to_dict()["input_tokens"] == 120 and c.usage.cached == 1


def test_datasheet_guard_flags_numbers_not_in_text():
    spec = {"mount": {"pattern": "rect", "a_mm": 31.0, "b_mm": 31.0, "hole_count": 4, "pcd_mm": None},
            "pilot_dia_mm": 22.0, "shaft_dia_mm": 5.0, "mass_kg": 0.28, "page": 2}
    text = "Hole spacing 31,0 mm  pilot Ø22 h7  shaft 5 mm"
    assert guard(spec, text) == ["mass_kg"]
