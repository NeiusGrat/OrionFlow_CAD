"""Vision reader without the network: conversion, cross-check, refusals, page failures."""

from drawcheck import extract_vision as ev
from drawcheck.model import Annotation, Drawing, Page
from drawcheck.parse import parse_fcf


def _page(i=0):
    return Page(index=i, width=1000.0, height=1000.0)


def test_frame_text_beats_empty_structured_datums():
    # Real ftc-08 output: structured datums empty, printed text has them.
    item = {"kind": "gdt_frame", "text": "⌖ Ø.023 Ⓜ F A B C", "box_2d": [10, 10, 20, 60],
            "characteristic": "position", "tolerance": 0.023, "datums": []}
    a = ev.to_annotation(item, _page())
    assert a.data["datums"] == ["A", "B", "C"] and a.data["material"] == "M" and a.data["modifiers"] == ["F"]


def test_frame_falls_back_to_structured_fields():
    item = {"kind": "gdt_frame", "text": "position frame", "box_2d": [10, 10, 20, 60],
            "characteristic": "perpendicularity", "tolerance": 0.05, "datums": ["A"]}
    assert ev.to_annotation(item, _page()).data["characteristic"] == "perpendicularity"


def test_box_conversion_and_illegible():
    a = ev.to_annotation({"kind": "dimension", "text": "50 ±0.1", "box_2d": [100, 200, 120, 300]}, _page())
    assert a.bbox == (200.0, 100.0, 300.0, 120.0) and a.data["upper"] == 0.1
    b = ev.to_annotation({"kind": "dimension", "text": "?", "box_2d": [1, 1, 2, 2]}, _page())
    assert b.data["illegible"]
    assert ev.to_annotation({"kind": "dimension", "text": "5", "box_2d": [5, 5, 1, 1]}, _page()) is None


def test_cross_check_confirms_conflicts_and_fills_headless():
    d = Drawing(source="x.pdf", pages=[_page()])
    vec_dim = Annotation("dimension", "50 ±0.1", 0, (100, 100, 150, 110), "vector",
                         {"nominal": 50.0, "upper": 0.1, "lower": -0.1, "fit": None, "count": 1})
    vec_other = Annotation("dimension", "30 ±0.2", 0, (400, 400, 450, 410), "vector",
                           {"nominal": 30.0, "upper": 0.2, "lower": -0.2, "fit": None, "count": 1})
    headless = Annotation("gdt_frame", "Ø.015 A B C", 0, (600, 600, 680, 612), "vector",
                          {"characteristic": None, "category": None, "headless": True, "tolerance": 0.015,
                           "datums": ["A", "B", "C"], "material": None})
    d.annotations += [vec_dim, vec_other, headless]
    found = [
        Annotation("dimension", "50 ±0.1", 0, (101, 99, 151, 111), "vision", dict(vec_dim.data)),
        Annotation("dimension", "38 ±0.2", 0, (401, 401, 451, 411), "vision",       # misread 30 as 38
                   {"nominal": 38.0, "upper": 0.2, "lower": -0.2, "fit": None, "count": 1}),
        Annotation("gdt_frame", "⌖ Ø.015 A B C", 0, (590, 598, 682, 613), "vision", parse_fcf("⌖ Ø.015 A B C")),
        Annotation("datum_feature", "D", 0, (800, 800, 812, 812), "vision", {"letter": "D"}),
    ]
    st = ev.merge(d, d.pages[0], found)
    assert st == {"confirmed": 2, "conflict": 1, "vision_only": 1, "duplicate": 0}
    assert vec_dim.source == "confirmed" and vec_other.source == "vector" and vec_other.data["nominal"] == 30.0
    assert headless.data["characteristic"] == "position" and headless.source == "vision"   # symbol unconfirmed
    assert any("38 ±0.2" in w for w in d.warnings)
    assert d.vision_pages == [0]


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_refusal_moves_to_next_model(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr(ev, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ev, "_api_key", lambda: "k")
    monkeypatch.setattr(ev, "FALLBACK_MODELS", ["m2"])
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "m1" in url:
            return _Resp(200, {"candidates": [{"finishReason": "RECITATION", "index": 0}]})
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"annotations": []}'}]}}],
                           "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})

    monkeypatch.setattr(httpx, "post", fake_post)
    result, usage = ev.call_gemini(b"png", model="m1")
    assert result == {"annotations": []} and usage["model"] == "m2"
    assert any("m1" in c for c in calls)


def test_one_failed_page_does_not_lose_the_others(monkeypatch):
    d = Drawing(source="x.pdf", pages=[_page(0), _page(1)])
    for p in d.pages:
        p.scanned, p.layer = True, "image"
    monkeypatch.setattr(ev, "_api_key", lambda: "k")

    def fake_read(path, page, model):
        if page.index == 0:
            raise ev.VisionUnavailable("all vision models overloaded")
        return [Annotation("note", "1. UNITS: MM", 1, (10, 10, 100, 20), "vision", {"units": "mm"})], {"seconds": 1}

    monkeypatch.setattr(ev, "read_page_image", fake_read)
    ev.extract(d, "x.pdf", [0, 1])
    assert d.vision_pages == [1] and d.vision_stats["failed_pages"] == 1
    assert any("page 1: vision reader failed" in w for w in d.warnings)
    from drawcheck import rules
    assert [f.page for f in rules.run(d) if f.rule == "RD-001"] == [0]


def test_real_ftc07_frames_parse():
    a = parse_fcf("⌖ Ø.040 Ⓜ Ø.045 MAX A B C")
    assert a["datums"] == ["A", "B", "C"] and a["max_tolerance"] == 0.045 and a["material"] == "M"
    b = parse_fcf("⌖ Ø.050 ST A B C")
    assert b["datums"] == ["A", "B", "C"] and "ST" in b["modifiers"]


def test_unparseable_frame_with_letters_is_unreadable_not_datumless():
    item = {"kind": "gdt_frame", "text": "⌖ Ø.04 ?? A B C", "box_2d": [10, 10, 20, 60],
            "characteristic": "position", "tolerance": 0.04, "datums": []}
    assert ev.to_annotation(item, _page()).data.get("unparsed")


def test_symbol_from_vision_on_headless_frame_stays_verify():
    # Text layer has '.04 A B C' (symbol drawn as geometry); only the model saw the symbol.
    d = Drawing(source="x.pdf", pages=[_page()])
    headless = Annotation("gdt_frame", ".04 A B C", 0, (100, 100, 180, 112), "vector",
                          {"characteristic": None, "category": None, "headless": True, "tolerance": 0.04,
                           "datums": ["A", "B", "C"], "material": None})
    d.annotations.append(headless)
    ev.merge(d, d.pages[0], [Annotation("gdt_frame", "∥ .04 A B C", 0, (98, 99, 182, 113), "vision",
                                        parse_fcf("∥ .04 A B C"))])
    assert headless.data["characteristic"] == "parallelism" and headless.source == "vision"
    assert headless.data["text_layer"] == ".04 A B C"


def test_same_datum_in_two_views_is_not_a_duplicate():
    d = Drawing(source="x.pdf", pages=[_page(0), _page(1)])
    d.annotations += [Annotation("datum_feature", "A", 0, (10, 10, 24, 24), "vector", {"letter": "A"}),
                      Annotation("datum_feature", "A", 1, (500, 500, 514, 514), "vector", {"letter": "A"})]
    from drawcheck import rules
    assert not [f for f in rules.run(d) if f.rule == "GD-007"]
    d.annotations.append(Annotation("datum_feature", "A", 0, (300, 300, 314, 314), "vector", {"letter": "A"}))
    assert [f for f in rules.run(d) if f.rule == "GD-007"]


def test_form_symbol_contradicting_confirmed_datums_is_refused():
    d = Drawing(source="x.pdf", pages=[_page()])
    headless = Annotation("gdt_frame", ".04 A B C", 0, (100, 100, 180, 112), "vector",
                          {"characteristic": None, "category": None, "headless": True, "tolerance": 0.04,
                           "datums": ["A", "B", "C"], "material": None})
    d.annotations.append(headless)
    ev.merge(d, d.pages[0], [Annotation("gdt_frame", "▱ .04 A B C", 0, (98, 99, 182, 113), "vision",
                                        parse_fcf("▱ .04 A B C"))])
    assert headless.data["characteristic"] is None and headless.source == "confirmed"
    from drawcheck import rules
    assert not [f for f in rules.run(d) if f.rule == "GD-002"]
    assert any("symbol left unread" in w for w in d.warnings)


def test_common_datum_with_modifiers():
    # NIST ftc-08: profile to datum D and a common datum H-J, both at MMB.
    f = parse_fcf("⌒ .015 D HⓂ-JⓂ")
    assert f["datums"] == ["D", "H-J"] and f["datum_modifiers"] == {"H": "M", "J": "M"}
    from drawcheck.parse import datum_letters
    assert datum_letters(f["datums"]) == ["D", "H", "J"]
