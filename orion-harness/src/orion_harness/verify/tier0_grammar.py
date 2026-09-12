"""T0 grammar tier (§7.2): schema and parameter-domain checks, < 1 ms.

For `ofl` submissions a syntax failure is classified as `parse_error`
upstream in execute/ofl.py, before this gate ever runs -- by the time a
submission reaches this gate it has already parsed and executed. For
`featuregraph` submissions the FeatureGraph pydantic schema is the grammar.
"""

from __future__ import annotations

from ..contracts import GateResult
from ..registry import register_verifier
from .context import VerifyContext


@register_verifier("tier0.schema", version="1.0.0")
def schema_valid(ctx: VerifyContext) -> GateResult:
    if ctx.kind == "featuregraph":
        from app.domain.feature_graph import FeatureGraph

        try:
            FeatureGraph.model_validate(ctx.payload)
        except Exception as e:
            return GateResult(name="schema_valid", passed=False, reason=f"schema_valid:{e}")
        return GateResult(name="schema_valid", passed=True)

    return GateResult(name="schema_valid", passed=True)
