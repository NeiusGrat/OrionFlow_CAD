"""
Agentic side of OrionFlow Studio.

Two endpoints power the conversational CAD experience:

  POST /api/chat   -> generate or modify build123d code from natural language
  POST /api/edit   -> deterministic parameter tweaks (regex first, LLM if needed)

Both gracefully degrade when GROQ_API_KEY isn't configured so the studio
remains usable as a manual editor.
"""
from __future__ import annotations

import os
import re
import json
import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("orionflow.studio.agentic")

router = APIRouter(prefix="/api", tags=["agentic"])


# ---------------------------------------------------------------------------
# Groq client - lazy import so the studio still runs without the dependency.
# ---------------------------------------------------------------------------

_GROQ_CLIENT = None
_GROQ_ERROR: Optional[str] = None
_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _groq():
    """Return (client, model) or (None, reason)."""
    global _GROQ_CLIENT, _GROQ_ERROR
    if _GROQ_CLIENT is not None:
        return _GROQ_CLIENT, _GROQ_MODEL
    if _GROQ_ERROR:
        return None, _GROQ_ERROR

    # Try the project's settings first; fall back to raw env vars.
    api_key = os.environ.get("GROQ_API_KEY")
    model = _GROQ_MODEL
    try:
        from app.config import settings  # type: ignore
        api_key = settings.groq_api_key or api_key
        model = getattr(settings, "llm_model", model) or model
    except Exception:
        pass

    if not api_key:
        _GROQ_ERROR = "GROQ_API_KEY not set"
        return None, _GROQ_ERROR
    try:
        from groq import Groq
    except ImportError:
        _GROQ_ERROR = "groq package not installed (pip install groq)"
        return None, _GROQ_ERROR

    try:
        _GROQ_CLIENT = Groq(api_key=api_key)
    except Exception as exc:
        _GROQ_ERROR = f"Groq init failed: {exc}"
        return None, _GROQ_ERROR
    globals()["_GROQ_MODEL"] = model
    return _GROQ_CLIENT, model


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CODEGEN_SYSTEM = """You are OrionFlow Studio's CAD copilot. You write build123d \
Python code from a user's request.

Strict rules:
- Always begin with: from build123d import *
- Put every dimension as a named variable near the top so they can be parameterised.
- Use `with BuildPart() as part:` for solids, `BuildSketch` for 2D, `Mode.SUBTRACT` for cuts.
- End with exactly: result = part.part
- Never call export_step/export_stl/export_gltf/show/show_object.
- Output ONLY raw Python. No markdown fences, no commentary, no leading text.
- Keep dimensions reasonable (mm). A washer is ~10mm, a small bracket is ~100mm.
  Never produce parts larger than 500mm unless the user asks for it explicitly.
"""

EDIT_SYSTEM = """You are editing existing build123d Python code based on a user's \
instruction. Output the COMPLETE updated script, never a diff.

Rules:
- Preserve the overall structure (variables, BuildPart, sketch order).
- Modify ONLY what the user asks for: parameter values, added features, removed features.
- Keep the final line as: result = part.part
- No markdown fences. No commentary. Output only Python code.
"""

FEWSHOT_GENERATE: List[Dict[str, str]] = [
    {
        "role": "user",
        "content": "M4 flat washer, 0.8mm thick, 9mm outer diameter.",
    },
    {
        "role": "assistant",
        "content": (
            "from build123d import *\n\n"
            "outer_d = 9.0\n"
            "inner_d = 4.3\n"
            "thickness = 0.8\n\n"
            "with BuildPart() as part:\n"
            "    with BuildSketch():\n"
            "        Circle(radius=outer_d / 2)\n"
            "        Circle(radius=inner_d / 2, mode=Mode.SUBTRACT)\n"
            "    extrude(amount=thickness)\n\n"
            "result = part.part\n"
        ),
    },
    {
        "role": "user",
        "content": "Round flange, 18mm OD, 4mm thick, 10mm long body of OD 10mm with 5mm bore.",
    },
    {
        "role": "assistant",
        "content": (
            "from build123d import *\n\n"
            "flange_d = 18.0\n"
            "flange_h = 4.0\n"
            "body_d   = 10.0\n"
            "body_h   = 10.0\n"
            "bore_d   = 5.0\n\n"
            "with BuildPart() as part:\n"
            "    with BuildSketch(Plane.XY):\n"
            "        Circle(flange_d / 2)\n"
            "    extrude(amount=flange_h)\n\n"
            "    with BuildSketch(Plane.XY.offset(flange_h)):\n"
            "        Circle(body_d / 2)\n"
            "    extrude(amount=body_h)\n\n"
            "    with BuildSketch(Plane.XY):\n"
            "        Circle(bore_d / 2)\n"
            "    extrude(amount=flange_h + body_h, mode=Mode.SUBTRACT)\n\n"
            "result = part.part\n"
        ),
    },
]


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_PARAM_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*$")

_EDIT_PATTERNS = [
    re.compile(r"set\s+(\w+)\s+to\s+([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"change\s+(\w+)\s+to\s+([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"make\s+(\w+)\s*=?\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"(\w+)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*(?:mm|cm)?\s*$", re.I),
]


def list_parameters(code: str) -> List[Dict[str, Any]]:
    """Pull top-of-file `name = number` lines so the UI can show sliders."""
    out = []
    for line in code.splitlines():
        m = _PARAM_RE.match(line.strip())
        if m:
            name, val = m.group(1), m.group(2)
            try:
                f = float(val)
            except ValueError:
                continue
            if name.isupper() or name.startswith("_"):
                continue
            out.append({"name": name, "value": f, "raw": val})
    return out


def heuristic_edit(code: str, prompt: str) -> Optional[Tuple[str, str]]:
    """Try `set X to Y` style edits without calling the LLM. Returns
    (new_code, human_reply) or None if no match."""
    params = {p["name"]: p for p in list_parameters(code)}
    if not params:
        return None
    for pat in _EDIT_PATTERNS:
        m = pat.search(prompt)
        if not m:
            continue
        name = m.group(1)
        try:
            new_val = float(m.group(2))
        except ValueError:
            continue

        target = None
        if name in params:
            target = name
        else:
            for k in params:
                if k.lower() == name.lower():
                    target = k
                    break
            if not target:
                for k in params:
                    kl, nl = k.lower(), name.lower()
                    if kl.startswith(nl) or nl.startswith(kl):
                        target = k
                        break
        if not target:
            continue

        old_val = params[target]["raw"]
        new_str = _format_number(new_val)
        line_re = re.compile(rf"^(\s*{re.escape(target)}\s*=\s*)[-+]?\d+(?:\.\d+)?", re.M)
        new_code, n = line_re.subn(lambda mo: mo.group(1) + new_str, code, count=1)
        if n == 0:
            continue
        return (
            new_code,
            f"Updated `{target}` from {old_val} to {new_str} (heuristic, no LLM call).",
        )
    return None


def _format_number(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


def _call_llm(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    client, model_or_err = _groq()
    if client is None:
        raise RuntimeError(model_or_err)
    response = client.chat.completions.create(
        model=model_or_err,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def _llm_generate(prompt: str, history: List[Dict[str, str]]) -> str:
    msgs: List[Dict[str, str]] = [{"role": "system", "content": CODEGEN_SYSTEM}]
    msgs.extend(FEWSHOT_GENERATE)
    for h in history[-6:]:
        if h.get("role") in {"user", "assistant"} and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": prompt})
    raw = _call_llm(msgs, temperature=0.15)
    return _strip_fences(raw)


def _llm_edit(prompt: str, current_code: str) -> str:
    msgs = [
        {"role": "system", "content": EDIT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current code:\n```python\n{current_code}\n```\n\n"
                f"Modify it as follows: {prompt}"
            ),
        },
    ]
    raw = _call_llm(msgs, temperature=0.15)
    return _strip_fences(raw)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    prompt: str
    history: List[ChatMessage] = Field(default_factory=list)
    current_code: str = ""
    mode: str = "auto"  # auto | generate | edit


class EditRequest(BaseModel):
    prompt: str
    current_code: str


class InspectRequest(BaseModel):
    face_index: int
    face_info: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Routing intent
# ---------------------------------------------------------------------------

_EDIT_KEYWORDS = (
    "change", "set", "make", "increase", "decrease", "bigger", "smaller",
    "taller", "shorter", "wider", "narrower", "add", "remove", "delete",
    "fillet", "chamfer", "this", "current", "it ", " it.", "update",
    "tweak", "adjust", "modify", "rename",
)


def _route(prompt: str, has_code: bool, mode: str) -> str:
    if mode in {"generate", "edit"}:
        return mode
    if not has_code:
        return "generate"
    low = prompt.lower()
    if any(kw in low for kw in _EDIT_KEYWORDS):
        return "edit"
    if len(prompt.split()) < 6 and any(c.isdigit() for c in prompt):
        return "edit"
    return "generate"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def status():
    client, info = _groq()
    return {
        "llm_ready": client is not None,
        "model": _GROQ_MODEL if client else None,
        "detail": info if client is None else "ok",
    }


@router.post("/chat")
def chat(req: ChatRequest):
    prompt = req.prompt.strip()
    if not prompt:
        return {"ok": False, "error": "empty prompt"}

    has_code = bool(req.current_code.strip())
    route = _route(prompt, has_code, req.mode)

    # Heuristic short-circuit for trivial parameter edits.
    if route == "edit":
        h = heuristic_edit(req.current_code, prompt)
        if h is not None:
            new_code, reply = h
            return {
                "ok": True,
                "route": "edit",
                "source": "heuristic",
                "code": new_code,
                "reply": reply,
                "parameters": list_parameters(new_code),
            }

    try:
        if route == "edit":
            new_code = _llm_edit(prompt, req.current_code)
            reply = "Applied edit."
        else:
            history = [m.model_dump() for m in req.history]
            new_code = _llm_generate(prompt, history)
            reply = "Generated new design."
    except Exception as exc:
        logger.exception("LLM call failed")
        return {
            "ok": False,
            "route": route,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "code": req.current_code,
            "reply": (
                "I couldn't reach the LLM — you can still write code manually. "
                f"({exc})"
            ),
        }

    if "result" not in new_code:
        new_code = new_code.rstrip() + "\n\nresult = part.part\n"

    return {
        "ok": True,
        "route": route,
        "source": "llm",
        "code": new_code,
        "reply": reply,
        "parameters": list_parameters(new_code),
    }


@router.post("/edit")
def edit(req: EditRequest):
    """Pure edit endpoint — prefer heuristic, fall back to LLM."""
    h = heuristic_edit(req.current_code, req.prompt)
    if h is not None:
        new_code, reply = h
        return {
            "ok": True,
            "source": "heuristic",
            "code": new_code,
            "reply": reply,
            "parameters": list_parameters(new_code),
        }
    try:
        new_code = _llm_edit(req.prompt, req.current_code)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "code": req.current_code,
            "reply": f"Edit failed: {exc}",
        }
    return {
        "ok": True,
        "source": "llm",
        "code": new_code,
        "reply": "Applied edit.",
        "parameters": list_parameters(new_code),
    }


@router.post("/inspect")
def inspect(req: InspectRequest):
    """Turn a selection event into a chat-ready snippet."""
    f = req.face_info or {}
    snippet_parts = [f"face {req.face_index}"]
    if "center" in f:
        c = f["center"]
        snippet_parts.append(f"at ({c[0]}, {c[1]}, {c[2]})")
    if "area" in f:
        snippet_parts.append(f"area {f['area']} mm²")
    return {
        "ok": True,
        "label": " · ".join(snippet_parts),
        "prefill": f"Add a 2 mm fillet to face {req.face_index}.",
    }


@router.post("/params/list")
def params_list(req: EditRequest):
    """Return the slider-eligible parameters parsed from current_code."""
    return {"ok": True, "parameters": list_parameters(req.current_code)}
