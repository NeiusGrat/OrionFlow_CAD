"""The real Claude request, against a local fake Messages endpoint (no key, no cost).

Checks what is sent (model, beta header, server-side fallbacks, structured-output
schema, cached system prompt, image) and that a streamed answer is parsed and
priced. The fake speaks the Messages streaming (SSE) protocol.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import drawcheck.extract_vision as ev

ANSWER = {"annotations": [{"kind": "dimension", "text": "Ø30 +0.021/0", "box": [100, 200, 180, 230],
                           "characteristic": "none", "tolerance": None, "basic": False, "diameter_zone": False,
                           "material_modifier": "none", "datums": [], "field": "none", "projection": "none"}]}


class _Fake(BaseHTTPRequestHandler):
    seen: dict = {}

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _Fake.seen = {"path": self.path, "headers": dict(self.headers), "body": body}
        text = json.dumps(ANSWER)
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"], "content": [],
                "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 3000, "output_tokens": 1, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 1500}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 800}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("request-id", "req_test")
        self.end_headers()
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()


@pytest.fixture()
def fake_api(monkeypatch, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(ev, "CACHE_DIR", tmp_path / "cache")
    yield
    server.shutdown()


def test_request_shape_and_parsing(fake_api):
    pytest.importorskip("anthropic")
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1000, 600), False)
    pix.clear_with(255)
    png = pix.tobytes("png")
    result, usage = ev.call_claude(png, (1000, 600), "claude-opus-5-5")

    seen = _Fake.seen
    body = seen["body"]
    assert seen["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in seen["headers"].get("anthropic-beta", "")
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["stream"] is True
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert body["output_config"]["effort"] == "high"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    img = body["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/png"
    assert "thinking" not in body and "temperature" not in body      # Opus 5.5 rejects both forms

    item = result["annotations"][0]
    assert item["box_2d"] == [333, 100, 383, 180]                     # pixels -> 0-1000, [ymin, xmin, ymax, xmax]
    assert item["characteristic"] is None
    # 3000 in x $4 + 800 out x $20 + 1500 cache-write x $5, per million
    assert usage["cost_usd"] == pytest.approx((3000 * 4 + 800 * 20 + 1500 * 5) / 1e6)
    assert usage["request_id"] == "req_test"

    # a second identical page is served from the disk cache: no second request
    _Fake.seen = {}
    again, u2 = ev.call_claude(png, (1000, 600), "claude-opus-5-5")
    assert again == result and u2["cached"] is True and _Fake.seen == {}
