"""Eval harness — run cases through the real agent loop and score from geometry.

Scores are computed from the synthetic ground truth and the tool trace, never
from the model's self-report. Query: grounding + numeric accuracy + an
unsupported-number (hallucination) penalty. Modify: edit success + survival +
intent match. The harness is pillar-agnostic; suites supply the cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.loop import AgentLoop
from orion_agent.harness.agent.verify import EditVerifier
from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel


@dataclass
class EvalCase:
    name: str
    pillar: str
    model: SyntheticModel
    prompt: str
    expect_numbers: list[float] = field(default_factory=list)   # must appear in answer
    expect_tools: list[str] = field(default_factory=list)       # must be called
    expect_param: Optional[tuple] = None                        # (key, value) after Modify
    expect_in_graph: list[float] = field(default_factory=list)  # must appear in compiled FeatureGraph
    tolerance: float = 0.05


@dataclass
class EvalResult:
    name: str
    pillar: str
    passed: bool
    grounded: bool
    accuracy: bool
    no_hallucination: bool
    tools_called: list[str]
    answer: str
    score: float
    detail: str = ""
    repair_attempts: int = 0
    repair_recovered: Optional[bool] = None   # None = no repair was needed


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for tok in _NUM_RE.findall(text):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= max(tol, tol * abs(b))


def _graph_numbers(obj, out=None) -> list[float]:
    """All numeric leaves of a (nested) FeatureGraph dict."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            _graph_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _graph_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(float(obj))
    return out


class EvalHarness:
    def __init__(self, llm, config=None):
        self.llm = llm
        self.config = config

    def run_case(self, case: EvalCase) -> EvalResult:
        bridge = SyntheticBridge(case.model)
        registry = build_registry(bridge, sandbox=None)
        loop = AgentLoop(self.llm, registry, bridge=bridge, config=self.config,
                         verifier=EditVerifier(bridge))
        result = loop.run(case.prompt, session_id=f"eval-{case.name}",
                          document=f"{case.model.name}.FCStd",
                          forced_pillar=case.pillar)

        tools_called = [c["name"] for c in result.tool_calls]
        answer = result.final_answer or ""

        # Tool-derived numbers = what the model is allowed to assert.
        supported = self._supported_numbers(result, case.model)
        answer_nums = _numbers(answer)

        # grounding: a quantitative query must have called at least one read tool
        grounded = any(c["ok"] for c in result.tool_calls) if case.expect_numbers else True

        # accuracy: every expected number appears in the answer (within tolerance)
        accuracy = all(
            any(_close(n, a, case.tolerance) for a in answer_nums)
            for n in case.expect_numbers
        ) if case.expect_numbers else True

        # hallucination: an asserted number not supported by any tool result and
        # not a trivially-derived value (allow simple arithmetic neighbours).
        unsupported = [
            n for n in answer_nums
            if not any(_close(n, s, case.tolerance) for s in supported)
            and not any(_close(n, e, case.tolerance) for e in case.expect_numbers)
        ]
        no_hallucination = len(unsupported) == 0

        # Modify intent check
        param_ok = True
        if case.expect_param is not None:
            key, value = case.expect_param
            param_ok = _close(float(bridge.model.parameters.get(key, "nan") or "nan")
                              if str(bridge.model.parameters.get(key)).replace(".", "").lstrip("-").isdigit()
                              else float("nan"), float(value), case.tolerance) \
                if isinstance(value, (int, float)) else (bridge.model.parameters.get(key) == value)

        tools_ok = all(t in tools_called for t in case.expect_tools)

        # Generate: the compiled FeatureGraph must carry the requested numbers
        # (dimensions live in the graph, not the prose answer).
        graph_ok = True
        if case.expect_in_graph:
            graph = getattr(bridge, "_compiled_graph", None)
            gnums = _graph_numbers(graph) if graph else []
            graph_ok = bool(graph) and all(
                any(_close(n, gval, case.tolerance) for gval in gnums)
                for n in case.expect_in_graph
            )

        checks = [grounded, accuracy, no_hallucination, param_ok, tools_ok, graph_ok]
        score = sum(1 for c in checks if c) / len(checks)
        passed = all(checks)

        detail = ""
        if not accuracy:
            detail += f"missing expected {case.expect_numbers} in answer nums {answer_nums}; "
        if not no_hallucination:
            detail += f"unsupported numbers {unsupported}; "
        if not tools_ok:
            detail += f"missing tools {set(case.expect_tools) - set(tools_called)}; "
        if not param_ok:
            detail += f"param {case.expect_param} not applied; "
        if not graph_ok:
            detail += f"graph missing expected values {case.expect_in_graph}; "

        repair = ((result.trajectory.validation.checks.get("repair")
                   if result.trajectory else None) or {})

        return EvalResult(
            name=case.name, pillar=case.pillar, passed=passed, grounded=grounded,
            accuracy=accuracy, no_hallucination=no_hallucination,
            tools_called=tools_called, answer=answer[:300], score=score, detail=detail.strip(),
            repair_attempts=len(repair.get("attempts", [])),
            repair_recovered=repair.get("recovered") if repair else None,
        )

    def run_suite(self, cases: list[EvalCase]) -> list[EvalResult]:
        return [self.run_case(c) for c in cases]

    @staticmethod
    def _supported_numbers(result, model: SyntheticModel) -> list[float]:
        # Numbers that legitimately appear from tool results / ground truth.
        nums = [
            model.faces, model.edges, model.vertices, model.holes, model.volume,
            *model.bbox,
        ]
        if model.hole_spacing is not None:
            nums.append(model.hole_spacing)
        nums.extend(model.parameters.values() if model.parameters else [])
        # Plus any number that appeared in a tool result preview.
        for c in result.tool_calls:
            nums.extend(_numbers(c.get("result_preview", "")))
        return [float(n) for n in nums if isinstance(n, (int, float))]
