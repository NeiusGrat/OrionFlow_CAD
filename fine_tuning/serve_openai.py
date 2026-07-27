"""Minimal OpenAI-compatible server for the fine-tuned OrionFlow model.

The AMD "Unsloth Studio" image ships the training stack but not vLLM, so this
fills the serving gap with zero extra dependencies (stdlib HTTP only). It speaks
just enough of ``/v1/chat/completions`` — including SSE streaming — for both
``orion_agent``'s VLLMClient and ``orion.eval_blueprint --endpoint`` to talk to
it unchanged.

This is a demo server, not a throughput engine: one generation at a time, no
continuous batching. That is the right shape for a live demo (a single user,
streaming the derivation as it is written) and the wrong shape for scoring
hundreds of samples — use ``generate_batch.py`` for that.

    python fine_tuning/serve_openai.py --adapter runs/orionflow-32b --port 8000

Prompts are framed exactly as in training; Qwen3's packaged chat template is
deliberately not used (it rewrites assistant turns and injects its own empty
<think> pair).
"""

from __future__ import annotations

try:
    from unsloth import FastLanguageModel          # must precede transformers
    _HAS_UNSLOTH = True
except Exception:                                   # noqa: BLE001
    _HAS_UNSLOTH = False

import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

IM_START, IM_END = "<|im_start|>", "<|im_end|>"

STATE: dict = {}
GPU_LOCK = threading.Lock()          # one generation at a time on one card


def render(messages: list[dict]) -> str:
    out = []
    for m in messages:
        out.append(f"{IM_START}{m.get('role', 'user')}\n{m.get('content', '')}"
                   f"{IM_END}\n")
    out.append(f"{IM_START}assistant\n")
    return "".join(out)


def load(adapter: str, base: str, max_seq: int):
    merged = (os.path.exists(os.path.join(adapter, "config.json"))
              and not os.path.exists(os.path.join(adapter,
                                                  "adapter_config.json")))
    src = adapter if merged else base
    print(f"loading {'merged model' if merged else f'{base} + {adapter}'}")
    if _HAS_UNSLOTH:
        model, tok = FastLanguageModel.from_pretrained(
            model_name=src, max_seq_length=max_seq, dtype=torch.bfloat16,
            load_in_4bit=False)
        if not merged:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
        FastLanguageModel.for_inference(model)
    else:
        tok = AutoTokenizer.from_pretrained(src)
        model = AutoModelForCausalLM.from_pretrained(
            src, torch_dtype=torch.bfloat16, device_map="auto")
        if not merged:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
        model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return model, tok


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):          # keep the console readable
        pass

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            return self._json(200, {"status": "ok"})
        if self.path.rstrip("/") == "/v1/models":
            return self._json(200, {"object": "list", "data": [
                {"id": STATE["name"], "object": "model", "owned_by": "orionflow"}]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError) as e:
            return self._json(400, {"error": f"bad request: {e}"})

        prompt = render(req.get("messages", []))
        max_new = int(req.get("max_tokens") or 2560)
        temp = float(req.get("temperature") or 0.0)
        if req.get("stream"):
            return self._stream(prompt, max_new, temp)

        with GPU_LOCK:
            text = self._generate(prompt, max_new, temp)
        self._json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": STATE["name"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
        })

    # ------------------------------------------------------------------ #
    def _gen_kwargs(self, prompt: str, max_new: int, temp: float) -> dict:
        model, tok = STATE["model"], STATE["tok"]
        enc = tok(prompt, return_tensors="pt").to(model.device)
        kw = dict(**enc, max_new_tokens=max_new,
                  eos_token_id=tok.convert_tokens_to_ids(IM_END),
                  pad_token_id=tok.pad_token_id)
        if temp > 0:
            kw.update(do_sample=True, temperature=temp)
        else:
            kw.update(do_sample=False)
        return kw

    def _generate(self, prompt: str, max_new: int, temp: float) -> str:
        model, tok = STATE["model"], STATE["tok"]
        kw = self._gen_kwargs(prompt, max_new, temp)
        with torch.no_grad():
            out = model.generate(**kw)
        gen = out[0][kw["input_ids"].shape[1]:]
        return tok.decode(gen, skip_special_tokens=True)

    def _stream(self, prompt: str, max_new: int, temp: float):
        model, tok = STATE["model"], STATE["tok"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        def frame(delta: dict, finish=None) -> bytes:
            return b"data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": STATE["name"],
                "choices": [{"index": 0, "delta": delta,
                             "finish_reason": finish}]}).encode() + b"\n\n"

        with GPU_LOCK:
            streamer = TextIteratorStreamer(
                tok, skip_prompt=True, skip_special_tokens=True)
            kw = self._gen_kwargs(prompt, max_new, temp)
            kw["streamer"] = streamer
            thread = threading.Thread(target=model.generate, kwargs=kw)
            thread.start()
            try:
                self.wfile.write(frame({"role": "assistant"}))
                for piece in streamer:
                    if piece:
                        self.wfile.write(frame({"content": piece}))
                        self.wfile.flush()
                self.wfile.write(frame({}, finish="stop"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass                       # client hung up mid-stream
            finally:
                thread.join()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-32B")
    ap.add_argument("--name", default="orionflow")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--max-seq", type=int, default=8192)
    args = ap.parse_args()

    model, tok = load(args.adapter, args.base, args.max_seq)
    STATE.update(model=model, tok=tok, name=args.name)
    print(f"serving {args.name} on {args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
