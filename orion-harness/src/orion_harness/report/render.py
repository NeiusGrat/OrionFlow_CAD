"""R10: "a bare mean is not a result." This module is the only place that
turns a RunSummary into text, and it refuses to print `overall_mean_score`
without also computing and printing the interval around it -- there is no
code path here that can produce a report with a mean and no CI.
"""

from __future__ import annotations

from ..score.aggregate import RunSummary
from ..score.stats import Interval, clustered_bootstrap_ci


def compute_overall_ci(
    scores_by_family: dict[str, list[float]], n_resamples: int = 10000
) -> Interval | None:
    if not any(scores_by_family.values()):
        return None
    return clustered_bootstrap_ci(scores_by_family, n_resamples=n_resamples)


def render_markdown(summary: RunSummary, overall_ci: Interval | None, title: str) -> str:
    lines = [f"# {title}", ""]

    if summary.overall_mean_score is None:
        lines.append("**Overall score:** no scored tasks (n=0 scored).")
    elif overall_ci is None:
        # R10: this should never happen if overall_mean_score is not None,
        # since the same scored results feed both -- fail loudly rather
        # than silently printing a bare mean.
        raise RuntimeError(
            "overall_mean_score is set but no CI was computed -- refusing to "
            "render a bare mean (R10)"
        )
    else:
        lines.append(
            f"**Overall score:** {overall_ci.point:.3f} "
            f"[{overall_ci.lo:.3f}, {overall_ci.hi:.3f}] "
            f"(95% bootstrap CI, clustered by family, {overall_ci.n_resamples} resamples, "
            f"n={summary.n_total})"
        )
    lines.append("")

    lines.append(f"**Status counts:** {_format_counts(summary.status_counts)}")
    n_error = summary.status_counts.get("error", 0)
    if summary.n_total and n_error / summary.n_total > 0.02:
        lines.append(
            f"\n> **Warning:** {n_error}/{summary.n_total} results are `error` "
            f"(>2%) -- this run is not valid per §6.3; fix the infra failure "
            f"before trusting any score above."
        )
    lines.append("")

    lines.append("## Per-family")
    lines.append("")
    lines.append("| family | n | n_scored | mean_score | status_counts |")
    lines.append("|---|---|---|---|---|")
    for fam in summary.by_family:
        mean_str = f"{fam.mean_score:.3f}" if fam.mean_score is not None else "n/a"
        lines.append(
            f"| {fam.family} | {fam.n} | {fam.n_scored} | {mean_str} | "
            f"{_format_counts(fam.status_counts)} |"
        )
    lines.append("")

    lines.append("## Gate failure counts")
    lines.append("")
    lines.append("| gate | n_failed | n_seen | failure_rate |")
    lines.append("|---|---|---|---|")
    for g in summary.gate_failures:
        rate = f"{g.n_failed / g.n_seen:.1%}" if g.n_seen else "n/a"
        lines.append(f"| {g.gate_name} | {g.n_failed} | {g.n_seen} | {rate} |")
    lines.append("")

    lines.append("## Timing")
    lines.append("")
    lines.append(f"median wall time: {summary.median_wall_s:.3f}s, p95: {summary.p95_wall_s:.3f}s")
    lines.append("")

    return "\n".join(lines)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "(none)"
