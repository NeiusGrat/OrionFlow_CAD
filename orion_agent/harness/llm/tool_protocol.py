"""Prompt-based tool-calling protocol.

k2v2 think is served through an OpenAI-style chat endpoint that does not expose
native function-calling, so tool calls are carried in the message content and
parsed back out here. This is the adapter-level normalisation the build plan
calls for: the agent loop always receives structured
:class:`~orion_agent.harness.llm.base.ToolCallRequest` objects, regardless of
whether the backend supports native tools.

A future vLLM backend with native tool calls can bypass this entirely.
"""

from __future__ import annotations

import json
import re
from typing import Any

from orion_agent.harness.llm.base import ToolCallRequest

_OPEN, _CLOSE = "<tool_call>", "</tool_call>"
# Fenced ```json {...}``` fallback (balanced extraction handles nesting).
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def render_tool_instructions(tool_schemas: list[dict]) -> str:
    """Build the system-prompt section describing how to call tools."""
    if not tool_schemas:
        return ""
    lines = [
        "You can call tools to inspect or modify the CAD model. The results of "
        "tool calls are real measurements from the live model — always prefer "
        "them over guessing.",
        "",
        "To call a tool, emit EXACTLY one tag on its own, then stop:",
        '<tool_call>{"name": "<tool>", "arguments": { ... }}</tool_call>',
        "",
        "Call one tool at a time and wait for its result before the next. When "
        "you have enough information, reply with your final answer as plain text "
        "and DO NOT emit a <tool_call> tag.",
        "",
        "Available tools:",
    ]
    for s in tool_schemas:
        fn = s.get("function", s)
        name = fn.get("name", "")
        desc = fn.get("description", "")
        props = (fn.get("parameters", {}) or {}).get("properties", {})
        arg_names = ", ".join(props.keys()) or "(none)"
        lines.append(f"- {name}({arg_names}): {desc}")
    return "\n".join(lines)


def _match_brace(text: str, start: int) -> int:
    """Return index just past the JSON object whose '{' is at ``start``.

    Brace-aware and string-aware so nested objects and braces inside strings do
    not confuse it. Returns -1 if unbalanced (truncated output).
    """
    depth = 0
    in_str = False
    escape = False
    for k in range(start, len(text)):
        ch = text[k]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    return -1


def _iter_tagged(content: str):
    """Yield (json_str, span_start, span_end) for each <tool_call> object.

    Tolerates a MISSING ``</tool_call>`` close tag (the model often omits it):
    the object is delimited by balanced braces starting at the first ``{`` after
    the open tag, with the optional close tag consumed if present.
    """
    pos = 0
    while True:
        i = content.find(_OPEN, pos)
        if i == -1:
            return
        brace = content.find("{", i + len(_OPEN))
        if brace == -1:
            return
        end = _match_brace(content, brace)
        if end == -1:
            return
        span_end = end
        tail = content[end:end + 24]
        close = tail.find(_CLOSE)
        if close != -1:
            span_end = end + close + len(_CLOSE)
        yield content[brace:end].strip(), i, span_end
        pos = span_end


def parse_tool_calls(content: str) -> list[ToolCallRequest]:
    """Extract tool-call requests from model output."""
    calls: list[ToolCallRequest] = []
    raw_jsons = [seg for seg, _, _ in _iter_tagged(content)]
    if not raw_jsons:
        raw_jsons = [m.group(1) for m in _FENCE_RE.finditer(content)]
    for raw in raw_jsons:
        obj = _safe_json(raw)
        if not obj or "name" not in obj:
            continue
        args = obj.get("arguments", obj.get("args", {}))
        if isinstance(args, str):
            args = _safe_json(args) or {}
        calls.append(ToolCallRequest.new(obj["name"], args if isinstance(args, dict) else {}))
    return calls


def strip_tool_calls(content: str) -> str:
    """Remove tool-call tags, leaving the human-facing answer text."""
    spans = [(i, j) for _, i, j in _iter_tagged(content)]
    for i, j in reversed(spans):
        content = content[:i] + content[j:]
    content = _FENCE_RE.sub(
        lambda m: "" if '"name"' in m.group(1) else m.group(0), content
    )
    # Drop any leftover <tool_call> that was truncated mid-emission (unbalanced
    # braces) so raw protocol text never reaches the user.
    orphan = content.find(_OPEN)
    if orphan != -1:
        brace = content.find("{", orphan + len(_OPEN))
        if brace == -1 or _match_brace(content, brace) == -1:
            content = content[:orphan]
    return content.strip()


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # tolerate trailing commas / single quotes
        try:
            return json.loads(text.replace("'", '"'))
        except Exception:  # noqa: BLE001
            return None
