"""§12: "Reward = the same verifier. No separate reward implementation,
ever (R1)." Every reward function here reads only `Result` (produced by
the same `evaluate_submission` the CLI and any future eval use) plus the
raw submission text for the format check -- none of them re-derive a
score from geometry themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import Result

DEFAULT_WEIGHTS = (1.0, 1.0, 0.1)  # (gates, metrics, format) -- §12


def gates_reward(result: Result, **_kw) -> float:
    if result.status != "scored":
        return 0.0
    return 1.0 if all(g.passed for g in result.gates) else 0.0


def metric_reward(result: Result, **_kw) -> float:
    """R2: a metric only means something once every gate has passed.
    Zero, not the raw §9.1 score, whenever any gate failed -- the score
    field is already 0.0 in that case (runner/jobs.py), but this
    recomputes it from the gates directly so the reward function does not
    silently depend on that invariant holding elsewhere."""

    if result.status != "scored" or not all(g.passed for g in result.gates):
        return 0.0
    return result.score if result.score is not None else 0.0


def format_reward(raw_completion: str, **_kw) -> float:
    """A small, capped signal for "did this look like a real attempt" --
    non-empty, not absurdly short, not absurdly long. Never the thing that
    decides whether a rollout is good; see Rubric.score's invariant test
    (tests/test_rl_rubric.py) that no failing-gate reward can exceed any
    passing-gate reward under DEFAULT_WEIGHTS."""

    length = len(raw_completion.strip())
    if length == 0:
        return 0.0
    if length < 10:
        return 0.3
    if length > 50_000:
        return 0.5
    return 1.0


@dataclass
class RewardBreakdown:
    total: float
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class Rubric:
    """verifiers-shape rubric: a weighted set of reward functions
    producing one scalar plus tracked component metrics (§1, "verifiers").
    Each func takes (result=..., raw_completion=...) and returns a float;
    unused kwargs are accepted and ignored so functions can have different
    signatures."""

    funcs: list
    weights: list[float]
    names: list[str] | None = None

    def __post_init__(self) -> None:
        if len(self.funcs) != len(self.weights):
            raise ValueError("funcs and weights must be the same length")
        if self.names is None:
            self.names = [getattr(f, "__name__", f"reward_{i}") for i, f in enumerate(self.funcs)]

    def score(self, **kwargs) -> RewardBreakdown:
        components = {}
        total = 0.0
        for name, func, weight in zip(self.names, self.funcs, self.weights):
            value = func(**kwargs)
            components[name] = value
            total += weight * value
        return RewardBreakdown(total=total, components=components)


def default_rubric() -> Rubric:
    w_gates, w_metric, w_format = DEFAULT_WEIGHTS
    return Rubric(
        funcs=[gates_reward, metric_reward, format_reward],
        weights=[w_gates, w_metric, w_format],
        names=["gates_reward", "metric_reward", "format_reward"],
    )
