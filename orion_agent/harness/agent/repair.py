"""Repair policy — typed failure classes, escalating strategies, a budget.

Before this module, repair was a reflex: a failed build tool returned its
error text and the model retried however it liked. This makes repair an
explicit policy the harness owns:

  * every failed build-tool call is classified into a typed error class,
  * each class maps to an ordered ladder of repair strategies (attempt 1 is a
    targeted fix, later attempts simplify, the final attempt authorises the
    fallback path),
  * a per-turn budget stops guided retries — after it, the model is told to
    stop repairing and report honestly,
  * every attempt is recorded in ``traj.validation.checks["repair"]`` so
    "repair recovery rate" is a measurable eval metric and repair
    trajectories become training data.

The policy only *guides* — the strategy text is appended to the tool
observation the model sees. The hard stop remains the loop's step cap.
Deterministic, stdlib-only.
"""

from __future__ import annotations

from typing import Optional

# Typed error classes.
GRAPH_INVALID = "graph_invalid"            # failed pre-compile validation
RECOMPUTE_FAILED = "recompute_failed"      # FreeCAD recompute error
ZERO_VOLUME = "zero_volume"                # compiled but produced no solid
SELECTOR_NO_MATCH = "selector_no_match"    # dress-up edge selector found nothing
SANDBOX_ERROR = "sandbox_error"            # write_code execution failed
IMPORT_FAILED = "import_failed"            # STEP artifact could not be placed
PARAMETER_REJECTED = "parameter_rejected"  # set_parameter / edit_feature refused
TRANSIENT = "transient"                    # bridge / connection hiccup
UNKNOWN = "unknown"

# Tools whose failures are repair-tracked (they build or mutate the model).
BUILD_TOOLS = {"create_featuregraph", "write_code", "import_shape",
               "set_parameter", "edit_feature"}

_TRANSIENT_CUES = ("bridge", "connection refused", "connection reset",
                   "timed out", "timeout", "unreachable", "not running")


def classify(tool_name: str, content: str = "", error: str = "") -> str:
    """Map a failed build-tool result to a typed error class."""
    text = f"{error} {content}".lower()
    if any(cue in text for cue in _TRANSIENT_CUES):
        return TRANSIENT
    if tool_name == "create_featuregraph":
        if error == "zero_volume" or "zero volume" in text:
            return ZERO_VOLUME
        if "matched no edges" in text or "no edges matched" in text:
            return SELECTOR_NO_MATCH
        if "featuregraph invalid" in text:
            return GRAPH_INVALID
        if error == "recompute_failed" or "recompute" in text:
            return RECOMPUTE_FAILED
        return UNKNOWN
    if tool_name == "write_code":
        return SANDBOX_ERROR
    if tool_name == "import_shape":
        return IMPORT_FAILED
    if tool_name in ("set_parameter", "edit_feature"):
        return PARAMETER_REJECTED
    return UNKNOWN


# Ordered strategy ladder per class: attempt 1, attempt 2, ... The last entry
# repeats for any later budgeted attempt.
_STRATEGIES: dict[str, list[str]] = {
    GRAPH_INVALID: [
        "Fix ONLY the listed validation errors and resubmit the graph "
        "otherwise unchanged. Common causes: line/arc profiles must close "
        "into a loop end-to-start; every profile op needs its sketch present "
        "in 'sketches'; Pad/Pocket need parameters.Length > 0.",
        "Simplify the graph: keep the base sketch and its Pad plus at most "
        "one cut. Get that compiling, then re-add the remaining features one "
        "at a time in separate calls.",
    ],
    RECOMPUTE_FAILED: [
        "Fix the named failing feature(s) only. Check: cuts must actually "
        "intersect the solid, Hole positions must lie on the solid, pattern "
        "spacing x occurrences must fit inside the part, and dress-up radius/"
        "size must be smaller than the adjacent faces.",
        "Remove the failing feature and everything that depends on it, "
        "compile the reduced graph first, then re-add the removed features "
        "one at a time in separate calls.",
    ],
    ZERO_VOLUME: [
        "The graph compiled but produced an empty solid: a profile is "
        "degenerate or a cut consumed the whole part. Check that sketch "
        "geometry encloses a non-zero area and Pocket/Groove depths are "
        "smaller than the solid's extent.",
    ],
    SELECTOR_NO_MATCH: [
        "The edge selector matched nothing. Use a different selector (all | "
        "top | bottom | vertical | horizontal | circular | straight | convex "
        "| concave | direction:<x|y|z> | radius:<mm> | largest:<n>) or drop "
        "this dress-up feature — a missing fillet/chamfer is better than a "
        "failed build.",
    ],
    SANDBOX_ERROR: [
        "Fix the Python error shown above. Remember: `from build123d import "
        "*` only (no submodule imports), assign the final solid to `result`, "
        "and do not call export functions.",
        "Rewrite the code from scratch with a simpler construction: "
        "primitive solids (Box, Cylinder) positioned with Pos(...) and "
        "combined with booleans, instead of sketch-based operations.",
    ],
    IMPORT_FAILED: [
        "Re-run write_code to regenerate the STEP artifact, then call "
        "import_shape with no path so it uses the latest artifact.",
    ],
    PARAMETER_REJECTED: [
        "Re-read the feature with get_parameters to confirm the exact "
        "property name and value type, then set it again with a valid value.",
    ],
    TRANSIENT: [
        "This looks transient (bridge/connection). Retry the exact same "
        "call once.",
    ],
    UNKNOWN: [
        "Diagnose before retrying: call list_objects / inspect_topology to "
        "see the current state, then fix the specific cause. Do not repeat "
        "the identical call.",
    ],
}

_FINAL_NOTE = (
    " This is the FINAL repair attempt: build the simplest valid version "
    "that satisfies the stated dimensions — drop dress-ups and secondary "
    "features if needed. If the FeatureGraph still fails, fall back to "
    "write_code + import_shape and tell the user the result is not "
    "parametric."
)

_EXHAUSTED = (
    "[repair budget exhausted after {budget} attempts] Do NOT retry the "
    "same approach again. Either make one fallback via write_code + "
    "import_shape, or finish now and report honestly exactly what failed "
    "and what, if anything, was built."
)


class RepairPolicy:
    """Per-turn repair state: classify failures, hand out escalating
    strategies, enforce the budget, and summarise for the trajectory."""

    def __init__(self, budget: int = 3):
        self.budget = max(1, int(budget))
        self.attempts: list[dict] = []
        self.recovered = False

    # ------------------------------------------------------------------ #
    def observe_failure(self, tool_name: str, content: str = "",
                        error: str = "") -> Optional[str]:
        """Record a failed build-tool call; return the guidance to append to
        the observation (None for tools that are not repair-tracked)."""
        if tool_name not in BUILD_TOOLS:
            return None
        error_class = classify(tool_name, content, error)
        attempt = len(self.attempts) + 1
        self.attempts.append({"tool": tool_name, "error_class": error_class,
                              "attempt": attempt})
        if attempt > self.budget:
            return _EXHAUSTED.format(budget=self.budget)
        ladder = _STRATEGIES[error_class]
        strategy = ladder[min(attempt, len(ladder)) - 1]
        if attempt == self.budget:
            strategy += _FINAL_NOTE
        return f"[repair {attempt}/{self.budget} — {error_class}] {strategy}"

    def observe_success(self, tool_name: str) -> None:
        """A build tool succeeded; if failures came before, the turn recovered."""
        if tool_name in BUILD_TOOLS and self.attempts:
            self.recovered = True

    # ------------------------------------------------------------------ #
    def summary(self) -> Optional[dict]:
        """Trajectory block; None when no repair was needed this turn."""
        if not self.attempts:
            return None
        return {
            "attempts": self.attempts,
            "budget": self.budget,
            "exhausted": len(self.attempts) >= self.budget,
            "recovered": self.recovered,
        }
