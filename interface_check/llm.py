"""The only place a language model is called. It reads messy inputs; it never decides.

Three tasks, each with a strict JSON schema, temperature 0, and a guard in the
caller that throws away anything not present in the input:

  match_bom        leftover BOM rows <-> leftover CAD part names
  read_datasheet   datasheet text + drawing pages -> component interface spec
  drawing_part     drawing title-block text -> which BOM part number it is

The provider is not chosen yet, so the client speaks the OpenAI-compatible
``/chat/completions`` shape (OpenAI, Gemini's OpenAI endpoint, Groq, vLLM,
OpenRouter and most gateways accept it). Configure with:

  INTERFACE_CHECK_LLM_URL           base URL, e.g. https://api.openai.com/v1
  INTERFACE_CHECK_LLM_KEY           bearer key
  INTERFACE_CHECK_LLM_MODEL         default model id
  INTERFACE_CHECK_LLM_MODEL_MATCH   cheap model for name matching (optional)
  INTERFACE_CHECK_LLM_MODEL_VISION  vision model for datasheets (optional)

Unset, :func:`from_env` returns :class:`NoLLM` and every caller degrades to the
deterministic passes — the run still completes, and the report says what the
model would have been asked. Another provider is one subclass of :class:`LLM`.
Responses are cached on disk by request hash, so re-running costs nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CACHE_DIR = Path(os.environ.get("INTERFACE_CHECK_CACHE", Path.home() / ".cache" / "interface_check"))


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    by_task: dict = field(default_factory=dict)

    def add(self, task: str, inp: int, out: int, secs: float, cached: bool) -> None:
        self.calls += 1
        self.cached += int(cached)
        self.input_tokens += inp
        self.output_tokens += out
        self.seconds += secs
        t = self.by_task.setdefault(task, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        t["calls"] += 1
        t["input_tokens"] += inp
        t["output_tokens"] += out

    def to_dict(self) -> dict:
        return {"calls": self.calls, "cached": self.cached, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "seconds": round(self.seconds, 2),
                "by_task": self.by_task}


class LLM:
    """Ask for JSON matching ``schema``. Subclasses implement :meth:`_complete`."""

    name = "base"

    def __init__(self) -> None:
        self.usage = Usage()

    @property
    def available(self) -> bool:
        return True

    def model_for(self, task: str) -> str:
        return ""

    def json(self, task: str, prompt: str, schema: dict, images: Iterable[bytes] = ()) -> dict:
        images = list(images)
        model = self.model_for(task)
        key = hashlib.sha256(json.dumps([self.name, model, prompt, schema]).encode()
                             + b"".join(hashlib.sha256(i).digest() for i in images)).hexdigest()
        cache = CACHE_DIR / f"{key}.json"
        if cache.exists():
            data = json.loads(cache.read_text())
            self.usage.add(task, 0, 0, 0.0, cached=True)
            return data
        t0 = time.time()
        data, inp, out = self._complete(task, model, prompt, schema, images)
        self.usage.add(task, inp, out, time.time() - t0, cached=False)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
        except OSError:
            pass
        return data

    def _complete(self, task, model, prompt, schema, images) -> tuple[dict, int, int]:
        raise NotImplementedError


class NoLLM(LLM):
    name = "none"

    @property
    def available(self) -> bool:
        return False

    def json(self, task, prompt, schema, images=()) -> dict:
        raise LLMUnavailable("no LLM configured (set INTERFACE_CHECK_LLM_URL / _KEY / _MODEL)")


class ChatCompletionsLLM(LLM):
    """OpenAI-compatible chat completions with ``response_format: json_schema``."""

    name = "chat-completions"

    def __init__(self, base_url: str, api_key: str, model: str, models: dict[str, str] | None = None,
                 timeout: float = 120.0, retries: int = 3):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.models = models or {}
        self.timeout = timeout
        self.retries = retries

    def model_for(self, task: str) -> str:
        return self.models.get(task) or self.model

    def _complete(self, task, model, prompt, schema, images):
        import httpx

        content: list[dict] | str = prompt
        if images:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
                for i in images]
        body = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": task, "strict": True, "schema": schema}},
        }
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                               headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.HTTPError as e:
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = LLMUnavailable(f"{r.status_code}: {r.text[:200]}")
                time.sleep(min(2 ** attempt, 4))
                continue
            if r.status_code >= 400:
                raise LLMUnavailable(f"LLM call failed {r.status_code}: {r.text[:300]}")
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return (json.loads(text), int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)))
        raise LLMUnavailable(f"LLM unreachable after {self.retries} tries: {last}")


SYSTEM = ("You transcribe and match engineering data. Use only what is in the input. "
          "When something is not stated, return null or leave it out. Never estimate a number.")


def from_env() -> LLM:
    url = os.environ.get("INTERFACE_CHECK_LLM_URL", "")
    key = os.environ.get("INTERFACE_CHECK_LLM_KEY", "")
    model = os.environ.get("INTERFACE_CHECK_LLM_MODEL", "")
    if not (url and key and model):
        return NoLLM()
    models = {"match_bom": os.environ.get("INTERFACE_CHECK_LLM_MODEL_MATCH", ""),
              "narrate": os.environ.get("INTERFACE_CHECK_LLM_MODEL_REPORT", ""),
              "drawing_part": os.environ.get("INTERFACE_CHECK_LLM_MODEL_MATCH", ""),
              "read_datasheet": os.environ.get("INTERFACE_CHECK_LLM_MODEL_VISION", "")}
    # The model is never on the critical path of a geometry result: a short timeout and
    # one retry, then every caller falls back to its deterministic path.
    return ChatCompletionsLLM(url, key, model, {k: v for k, v in models.items() if v},
                              timeout=float(os.environ.get("INTERFACE_CHECK_LLM_TIMEOUT", "20")),
                              retries=int(os.environ.get("INTERFACE_CHECK_LLM_RETRIES", "2")))


# ------------------------------------------------------------------ tasks

MATCH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"matches": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"bom_row": {"type": "integer"}, "cad_name": {"type": "string"},
                       "confidence": {"type": "number"}},
        "required": ["bom_row", "cad_name", "confidence"]}}},
    "required": ["matches"]}


def match_bom(llm: LLM, rows: list, cad_names: list[str]) -> list[tuple[int, str, float]]:
    """Leftover BOM rows -> CAD names. The caller drops anything not in its input."""
    listing = [{"bom_row": r.index, "part_number": r.part_number, "name": r.name, **r.extra} for r in rows]
    prompt = ("Match each BOM row to at most one CAD part name. Only match when they clearly refer to the "
              "same part (abbreviation, typo, vendor vs internal name). Each CAD name may be used once. "
              "confidence is 0..1. Leave a row out when unsure.\n"
              f"BOM rows: {json.dumps(listing)}\nCAD part names: {json.dumps(cad_names)}")
    data = llm.json("match_bom", prompt, MATCH_SCHEMA)
    out = []
    for m in data.get("matches", []):
        try:
            out.append((int(m["bom_row"]), str(m["cad_name"]), float(m["confidence"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


_NUM = {"type": ["number", "null"]}
DATASHEET_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "type": {"type": "string", "enum": ["motor", "servo", "bearing", "actuator", "other"]},
        "mount": {"type": "object", "additionalProperties": False,
                  "properties": {"pattern": {"type": ["string", "null"], "enum": ["rect", "circle", None]},
                                 "a_mm": _NUM, "b_mm": _NUM, "pcd_mm": _NUM,
                                 "hole_count": {"type": ["integer", "null"]},
                                 "thread": {"type": ["string", "null"]}},
                  "required": ["pattern", "a_mm", "b_mm", "pcd_mm", "hole_count", "thread"]},
        "pilot_dia_mm": _NUM, "shaft_dia_mm": _NUM, "bore_mm": _NUM, "od_mm": _NUM, "width_mm": _NUM,
        "mass_kg": _NUM,
        "page": {"type": ["integer", "null"]},
    },
    "required": ["name", "type", "mount", "pilot_dia_mm", "shaft_dia_mm", "bore_mm", "od_mm", "width_mm",
                 "mass_kg", "page"]}


def read_datasheet(llm: LLM, text: str, images: list[bytes]) -> dict:
    prompt = ("From this component datasheet, extract the mechanical interface in millimetres and kilograms. "
              "mount = the mounting hole pattern (rect: a_mm x b_mm hole spacing; circle: pcd_mm). "
              "Return null for any value the datasheet does not state. page = 1-based page of the "
              "dimension drawing.\nDatasheet text layer:\n" + text[:30000])
    return llm.json("read_datasheet", prompt, DATASHEET_SCHEMA, images)


DRAWING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"part_number": {"type": ["string", "null"]}, "revision": {"type": ["string", "null"]}},
    "required": ["part_number", "revision"]}


def drawing_part(llm: LLM, text: str, candidates: list[str]) -> dict:
    prompt = ("This is the text of an engineering drawing. Which of these part numbers is the drawing of "
              "(title block), and what revision does it show? Answer null if none.\n"
              f"Candidates: {json.dumps(candidates)}\nDrawing text:\n{text[:8000]}")
    return llm.json("drawing_part", prompt, DRAWING_SCHEMA)



# ------------------------------------------------------------------ narrative

NARRATIVE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "points": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "cites"]}}},
    "required": ["summary", "points"]}

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def _numbers_in(obj) -> set[float]:
    out: set[float] = set()
    for m in _NUMBER.finditer(json.dumps(obj)):
        try:
            out.add(round(abs(float(m.group())), 3))
        except ValueError:
            pass
    return out


def _grounded(text: str, allowed: set[float]) -> bool:
    """Every number in the text is in the facts; small whole numbers (counts like "4 holes") are allowed."""
    for m in _NUMBER.finditer(text):
        v = round(abs(float(m.group())), 3)
        if v in allowed or (v.is_integer() and v <= 20):
            continue
        return False
    return True


def deterministic_narrative(report: dict) -> dict:
    s = report["summary"]
    high = [f for f in report["findings"] if f["severity"] == "high"]
    text = (f"{s['high']} high, {s['medium']} medium, {s['low']} low and {s['info']} informational findings "
            f"across {report['stats'].get('parts', 0)} parts.")
    return {"status": "deterministic", "summary": text,
            "points": [{"text": f["message"], "cites": [f["fingerprint"]]} for f in high[:5]], "dropped": 0}


def narrate(llm: LLM, report: dict) -> dict:
    """Plain-language report text. Every point cites findings; numbers must come from them."""
    if not getattr(llm, "available", False):
        return deterministic_narrative(report)
    facts = [{k: f[k] for k in ("fingerprint", "rule_id", "severity", "message", "measured", "expected", "parts")}
             for f in report["findings"] if f["severity"] != "info"][:80]
    if not facts:
        return deterministic_narrative(report)
    prompt = ("Write an engineering summary of these assembly check findings for the design team. "
              "Every point must cite the fingerprints of the findings it is based on. Do not state any "
              "measurement that is not in the findings. Do not speculate about causes.\n"
              f"Findings: {json.dumps(facts)}")
    try:
        data = llm.json("narrate", prompt, NARRATIVE_SCHEMA)
    except Exception as e:  # noqa: BLE001 - rate limit, timeout, bad JSON: the report never waits on it
        out = deterministic_narrative(report)
        out.update(status="fallback", reason=f"{type(e).__name__}: {str(e)[:160]}")
        return out
    by_fp = {f["fingerprint"]: f for f in facts}
    points, dropped = [], 0
    for p in data.get("points", []):
        cites = [c for c in p.get("cites", []) if c in by_fp]
        if not cites or not _grounded(p.get("text", ""), _numbers_in([by_fp[c] for c in cites])):
            dropped += 1
            continue
        points.append({"text": p["text"], "cites": cites})
    summary = data.get("summary", "")
    if not _grounded(summary, _numbers_in(facts) | _numbers_in(report["summary"])):
        summary, dropped = deterministic_narrative(report)["summary"], dropped + 1
    return {"status": "llm", "summary": summary, "points": points, "dropped": dropped}
