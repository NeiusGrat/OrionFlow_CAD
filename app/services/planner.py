"""The Engineering Planner: decide the numbers, never touch the sentence.

Everything downstream of this is already deterministic — the schema says which
variables a family has, the medians give a baseline that has verified before,
the guards say what must hold, and the renderer emits a prompt byte-identical to
training. What is missing is judgement: *should* this plate be 10 mm or 6 mm,
and why. That is the one thing a model is better at than a table, so that is the
only thing it is asked for.

The shape of the ask matters more than the model. A planner that emits a whole
specification can invent variable names, miss required ones, and produce a part
nobody can trace. So it emits **overrides against a working baseline**:

    [{"variable": "pt", "value": 6.0, "why": "6 mm is the thinnest section that
      still gives full M4 thread engagement in 6061 (calculated 5.9 mm)"}]

Every override is checked against the mined schema before it is applied — the
name must be one this family actually carries — and the family's own guards are
re-evaluated afterwards. An override that would break a guard is refused with
the arithmetic attached, so the planner is told exactly what it did rather than
discovering it three stages later as a refused build.

Two rules inherited from the rest of the system and worth restating:

* This runs on the **base** model, never the Blueprint adapter. The adapter
  answers everything with a Blueprint; asking it to plan returns geometry where
  a decision belongs.
* Nothing the planner learns reaches the design prompt. It sets variables. The
  citations and calculations travel in ``EngineeringSpecification.grounding()``.
"""

from __future__ import annotations

import inspect
import json
import os
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.logging_config import get_logger
from app.services.engineering_spec import (
    EngineeringSpecification,
    specification_from_intent,
)

logger = get_logger(__name__)

#: How many tool rounds the planner may take before it must decide.
PLAN_TOOL_ROUNDS = 4

PLANNER_SYSTEM = """You are a mechanical design engineer choosing dimensions for \
a part. You do not draw, model, or calculate — tools calculate, and a separate \
system builds the geometry.

You will be given a part family, the exact variables it has, the range each has \
taken in verified parts, the constraints that must hold, and a working baseline. \
The baseline already builds. Your job is to improve it for the user's actual \
request and justify every change.

Rules:
- Only change what the request or engineering judgement requires. An unchanged \
baseline value is a fine answer.
- You may only set variables from the list you are given. There are no others.
- Never do arithmetic yourself. Call a calculator.
- Cite a standard when one governs the choice. Call a lookup tool.
- Every constraint expression shown must stay greater than zero.

When you are done, reply with ONLY a JSON array of overrides and nothing else:

[{"variable": "<name>", "value": <number>, "why": "<one sentence>"}]

An empty array [] means the baseline is already right."""


@dataclass
class PlanResult:
    specification: Optional[EngineeringSpecification] = None
    baseline: dict[str, float] = field(default_factory=dict)
    applied: list[dict] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)
    guards: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    model: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.specification is not None and not self.error


# --------------------------------------------------------------------------- #
# calculators as tools
# --------------------------------------------------------------------------- #
_JSON_TYPE = {float: "number", int: "integer", str: "string", bool: "boolean"}


def calculator_tools() -> list[dict]:
    """Tool schemas generated from ``orion.calc.CALCULATORS`` signatures.

    Generated rather than written so a new calculator becomes available to the
    planner by existing, not by being registered in a second place that can fall
    out of step with the first.

    Calculators taking structured input (a whole Blueprint, a list of parts) are
    skipped: they are for the harness, not for a model to call by hand.
    """
    from orion import calc

    tools: list[dict] = []
    for name, fn in sorted(calc.CALCULATORS.items()):
        try:
            # eval_str resolves the annotations of modules using
            # ``from __future__ import annotations``, where they arrive as
            # strings and every structural check silently sees nothing.
            sig = inspect.signature(fn, eval_str=True)
        except (TypeError, ValueError, NameError):
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
        props: dict[str, Any] = {}
        required: list[str] = []
        structured = False
        for pname, param in sig.parameters.items():
            annotation = param.annotation
            # ``list[dict]`` is not ``list``, so the origin has to be checked
            # too or a structured argument is advertised as a plain number.
            container = typing.get_origin(annotation) or annotation
            if container in (dict, list) or pname in (
                "payload",
                "parts",
                "thinking",
                "variables",
            ):
                structured = True
                break
            props[pname] = {"type": _JSON_TYPE.get(annotation, "number")}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        if structured or not props:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f"calc_{name}",
                    "description": (inspect.getdoc(fn) or name).split("\n\n")[0],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return tools


def _run_calculator(name: str, arguments: dict) -> str:
    from orion import calc

    try:
        result = calc.run(name[len("calc_") :], **(arguments or {}))
    except Exception as exc:  # noqa: BLE001 — surfaced to the model
        return f"calculator error: {exc}"
    return json.dumps(
        {k: (round(v, 6) if isinstance(v, float) else v) for k, v in result.items()},
        default=str,
    )


# --------------------------------------------------------------------------- #
def _brief(spec: EngineeringSpecification, message: str, questions: list[str]) -> str:
    """Everything the planner needs and nothing it does not."""
    from orion.family_schema import check_guards, describe

    lines = [
        f"The user asked: {message}",
        "",
        describe(spec.part_class),
        "",
        "Working baseline (already builds):",
    ]
    lines += [f"  {k} = {v:g}" for k, v in sorted(spec.variables.items())]

    guards = check_guards(spec.part_class, spec.variables)
    if guards:
        broken = [g for g in guards if not g["holds"]]
        lines.append("")
        lines.append("Constraints at the baseline (each must stay > 0):")
        lines += [
            f"  {g['id']}: {g['expr']} = {g['value']:.3f}"
            + ("   <-- VIOLATED, you must fix this" if not g["holds"] else "")
            for g in guards
        ]
        if broken:
            lines.append("")
            lines.append(
                "The baseline does not currently build. The dimensions "
                "the user gave are fixed; change a default instead."
            )
    if spec.material or spec.process:
        lines.append("")
        lines.append(
            f"Material: {spec.material or 'unstated'}; "
            f"process: {spec.process or 'unstated'}"
        )
    if questions:
        lines.append("")
        lines.append("Unresolved from the request:")
        lines += [f"  - {q}" for q in questions]

    # The output contract is restated here, at the end of the last message,
    # because the backend appends its own tool preamble to the system prompt —
    # a block written for the FreeCAD copilot that talks about inspecting "the
    # live model" and ends by asking for the final answer "as plain text".
    # There is no live model during planning, and plain text is the opposite of
    # what this stage needs. Whatever the system prompt said, this is read last.
    lines += [
        "",
        "There is no CAD model yet — nothing to inspect or measure. The tools "
        "available to you compute engineering quantities and look up standards.",
        "",
        "Reply with ONLY a JSON array of overrides, no prose before or after:",
        '[{"variable": "<name>", "value": <number>, "why": "<one sentence>"}]',
        "Use [] if the baseline is already right.",
    ]
    return "\n".join(lines)


def _parse_overrides(text: str) -> list[dict]:
    """The JSON array of overrides, tolerating a fence and surrounding prose."""
    body = text.strip()
    if "</think>" in body:
        body = body.rpartition("</think>")[2].strip()
    if "```" in body:
        parts = body.split("```")
        for chunk in parts[1::2]:
            chunk = (
                chunk.split("\n", 1)[-1] if chunk.lstrip().startswith("json") else chunk
            )
            body = chunk.strip()
            break
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return []
    return [row for row in parsed if isinstance(row, dict)]


def apply_overrides(
    spec: EngineeringSpecification, overrides: list[dict]
) -> tuple[EngineeringSpecification, list[dict], list[dict]]:
    """``(new_spec, applied, refused)``.

    An override is refused when it names a variable the family does not carry,
    when the value is not a number, or when applying it would break one of the
    family's own guards. The last is the important one: it is the difference
    between telling the planner "that makes the hole break the edge, by 1.2 mm"
    and letting the verifier refuse the part several stages later with the
    reason no longer attached to the decision that caused it.
    """
    from orion.family_schema import check_guards, for_family

    schema = for_family(spec.part_class)
    known = set(schema.variables) if schema else set()
    variables = dict(spec.variables)
    rationale = dict(spec.rationale)
    applied: list[dict] = []
    refused: list[dict] = []

    for row in overrides:
        name = str(row.get("variable", "")).strip()
        value = row.get("value")
        why = str(row.get("why", "")).strip()
        if known and name not in known:
            refused.append(
                {
                    **row,
                    "reason": f"{name!r} is not a {spec.part_class} variable; "
                    f"known: {', '.join(sorted(known))}",
                }
            )
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            refused.append({**row, "reason": f"value {value!r} is not a number"})
            continue

        trial = {**variables, name: float(value)}
        broken = [g for g in check_guards(spec.part_class, trial) if not g["holds"]]
        if broken:
            first = broken[0]
            refused.append(
                {
                    **row,
                    "reason": f"would violate {first['id']}: {first['expr']} "
                    f"= {first['value']:.3f}, must be > 0",
                }
            )
            continue

        variables = trial
        rationale[name] = why or "changed by the planner"
        applied.append({"variable": name, "value": float(value), "why": why})

    updated = EngineeringSpecification(
        part_class=spec.part_class,
        variables=variables,
        function=spec.function,
        manufacturing=spec.manufacturing,
        rationale=rationale,
        citations=list(spec.citations),
        calculations=dict(spec.calculations),
        constraints=list(spec.constraints),
        material=spec.material,
        process=spec.process,
    )
    return updated, applied, refused


# --------------------------------------------------------------------------- #
class EngineeringPlanner:
    """Intent in, justified specification out.

    ``complete`` is injected so this is testable without an endpoint and so the
    caller decides which model answers. It takes ``(messages, tools)`` and
    returns an object with ``.content`` and ``.tool_calls``. When it is None the
    planner returns the deterministic baseline — which is a real answer, not a
    failure: the medians build.
    """

    def __init__(
        self, complete: Optional[Callable] = None, tool_rounds: int = PLAN_TOOL_ROUNDS
    ):
        self._complete = complete
        self._rounds = tool_rounds

    # ------------------------------------------------------------------ #
    def baseline(
        self, message: str, intent=None
    ) -> tuple[Optional[EngineeringSpecification], list[str]]:
        """The deterministic half: intent, family, canonical variables, medians."""
        if intent is None:
            from orion_agent.harness.spec import SpecParser

            intent = SpecParser().parse(message)
        return specification_from_intent(intent, part_hint=message)

    # ------------------------------------------------------------------ #
    def plan(self, message: str, intent=None) -> PlanResult:
        from orion.family_schema import check_guards

        spec, questions = self.baseline(message, intent)
        if spec is None:
            return PlanResult(
                questions=questions, error="could not identify the part family"
            )

        result = PlanResult(
            specification=spec,
            baseline=dict(spec.variables),
            questions=questions,
            guards=check_guards(spec.part_class, spec.variables),
        )
        if self._complete is None:
            return result  # the baseline is a working part

        tools = calculator_tools() + _knowledge_schemas()
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": _brief(spec, message, questions)},
        ]

        text = ""
        for _round in range(self._rounds):
            try:
                response = self._complete(messages, tools)
            except Exception as exc:  # noqa: BLE001 — baseline still stands
                logger.warning("planner_completion_failed", error=str(exc))
                result.error = f"planner model unavailable: {exc}"
                return result
            if response is None:
                result.error = "planner model unreachable"
                return result

            calls = getattr(response, "tool_calls", None) or []
            if not calls:
                text = getattr(response, "content", "") or ""
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(response, "content", "") or "",
                    "tool_calls": calls,
                }
            )
            for call in calls:
                observation = _dispatch(call.name, call.arguments)
                result.tools_used.append(call.name)
                messages.append(
                    {
                        "role": "tool",
                        "name": call.name,
                        "tool_call_id": call.id,
                        "content": observation,
                    }
                )

        result.model = getattr(self._complete, "label", "")
        updated, applied, refused = apply_overrides(spec, _parse_overrides(text))
        result.specification = updated
        result.applied = applied
        result.refused = refused
        result.guards = check_guards(updated.part_class, updated.variables)
        return result


def live_completion(
    model: Optional[str] = None, provider: str = "vllm", retries: int = 3
):
    """A completion bound to the served model, for ``EngineeringPlanner``.

    Defaults to the **base** adapter. Planning on the Blueprint adapter returns
    a Blueprint — it was trained to answer everything that way — so the model
    that reasons and the model that draws are deliberately different weights on
    the same endpoint.

    Sequential with retries because the endpoint answers one request at a time;
    a concurrent burst comes back as dropped connections, and a dropped
    connection scored as a planning failure would be a measurement of the
    network rather than the model.
    """
    import time

    from orion_agent.harness.llm import get_llm_client
    from orion_agent.harness.llm.base import LLMMessage
    from orion_agent.shared.config import get_config

    client = get_llm_client(provider, config=get_config())
    chosen = model or os.environ.get("ORION_CONVERSATION_MODEL", "orionflow-base")

    def to_message(row: dict) -> LLMMessage:
        role = row.get("role")
        if role == "tool":
            return LLMMessage.tool(
                row.get("content", ""), row.get("tool_call_id", ""), row.get("name", "")
            )
        if role == "assistant":
            return LLMMessage.assistant(
                row.get("content", ""), tool_calls=row.get("tool_calls") or []
            )
        return LLMMessage(role, row.get("content", ""))

    def complete(messages: list[dict], tools: Optional[list[dict]]):
        wire = [to_message(m) for m in messages]
        last = None
        for attempt in range(retries):
            try:
                response = client.chat(
                    wire,
                    tools=tools or None,
                    temperature=0.0,
                    max_tokens=1024,
                    model=chosen,
                )
            except Exception as exc:  # noqa: BLE001 — transport, not the model
                last = exc
                time.sleep(2 * (attempt + 1))
                continue
            if response.finish_reason == "error" or str(response.content).startswith(
                "[vllm transport error"
            ):
                last = RuntimeError(str(response.content)[:120])
                time.sleep(2 * (attempt + 1))
                continue
            return response
        raise RuntimeError(f"planner endpoint unreachable: {last}")

    complete.label = f"{provider}:{chosen}"
    return complete


def _knowledge_schemas() -> list[dict]:
    try:
        from app.services.studio_agent import _knowledge_registry

        registry = _knowledge_registry()
        return registry.schemas() if registry else []
    except Exception:  # noqa: BLE001 — grounding is optional
        return []


def _dispatch(name: str, arguments: dict) -> str:
    """Run one tool call. Calculators first, then the knowledge registry."""
    if name.startswith("calc_"):
        return _run_calculator(name, arguments)
    try:
        from app.services.studio_agent import _knowledge_registry

        registry = _knowledge_registry()
        if registry is None:
            return f"tool {name} unavailable"
        return registry.execute(name, arguments or {}).content
    except Exception as exc:  # noqa: BLE001
        return f"tool {name} failed: {exc}"
