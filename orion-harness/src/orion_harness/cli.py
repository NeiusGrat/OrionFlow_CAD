"""`orion-harness` CLI (§10). `run`/`verify`/`selftest` exercise oracle
submissions end to end (no live model adapter yet -- that is §11, not
milestoned for M1/M2 here, see the final report for why). `report`,
`compare`, and `power` are real: they call score/stats.py so a mean is
never printed without its interval (R10). `tasks lint` statically checks
the task suite against the registry and family list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from ._repo_root import ensure_repo_root_on_path
from .contracts import EnvDigest, Submission

ensure_repo_root_on_path()  # orionflow_ofl / app.* live one level up (R1)

from .report.render import compute_overall_ci, render_markdown
from .report.run_log import RunLog
from .runner.cache import ResultCache
from .runner.evaluate import evaluate_submission
from .runner.pool import WorkerPool
from .score.aggregate import summarize
from .score.stats import minimum_detectable_effect, paired_delta_ci
from .tasks.lint import lint_tasks_root
from .tasks.loader import load_split, load_task_file


def _env_digest() -> EnvDigest:
    import build123d

    return EnvDigest(
        harness_version=__version__,
        solver_versions={"build123d": getattr(build123d, "__version__", "unknown")},
    )


def _oracle_submission(task_id: str, oracles_root: Path) -> Submission | None:
    for ext, kind in (
        (".ofl.py", "ofl"),
        (".b123d.py", "build123d"),
        (".json", "featuregraph"),
    ):
        p = oracles_root / f"{task_id}{ext}"
        if p.exists():
            return Submission(
                task_id=task_id,
                kind=kind,
                payload=p.read_text(encoding="utf-8"),
                model_id="oracle",
            )
    return None


def run_split(
    tasks_root: Path, oracles_root: Path, split: str, out_dir: Path | None, n_workers: int
) -> list:
    tasks = load_split(tasks_root, split)
    env = _env_digest()
    cache = ResultCache(out_dir / "cache" if out_dir else Path(".orion_harness_cache"))
    log = RunLog(out_dir) if out_dir else None
    if log:
        log.write_run_config(env, split, sys.argv, model_id="oracle")
    results = []
    with WorkerPool(n_workers=n_workers) as pool:
        for task in tasks:
            submission = _oracle_submission(task.task_id, oracles_root)
            if submission is None:
                print(f"  SKIP  {task.task_id}: no oracle found under {oracles_root}")
                continue
            result = evaluate_submission(task, submission, pool, cache, env)
            if log:
                log.append(result)
            results.append((task, result))
            marker = "PASS" if result.score == 1.0 else "FAIL"
            print(f"  {marker}  {task.task_id}  status={result.status} score={result.score}")
    return results


def cmd_run(args: argparse.Namespace) -> int:
    results = run_split(
        Path(args.tasks_root),
        Path(args.oracles_root),
        args.split,
        Path(args.out) if args.out else None,
        args.concurrency,
    )
    n_scored = sum(1 for _, r in results if r.status == "scored")
    n_error = sum(1 for _, r in results if r.status == "error")
    print(f"\n{len(results)} tasks, {n_scored} scored, {n_error} error")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    task = load_task_file(args.task)
    payload = Path(args.submission).read_text(encoding="utf-8")
    kind = "featuregraph" if args.submission.endswith(".json") else "ofl"
    submission = Submission(
        task_id=task.task_id, kind=kind, payload=payload, model_id=args.model_id
    )
    env = _env_digest()
    cache = ResultCache(Path(".orion_harness_cache"))
    with WorkerPool(n_workers=1) as pool:
        result = evaluate_submission(task, submission, pool, cache, env)
    print(result.model_dump_json(indent=2))
    return 0 if result.score == 1.0 else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    if not args.oracles:
        print("orion-harness selftest: pass --oracles (no other self-test category exists yet)")
        return 2

    tasks_root = Path(args.tasks_root)
    oracles_root = Path(args.oracles_root)
    failures = []
    for split in ("dev", "frozen"):
        results = run_split(tasks_root, oracles_root, split, None, args.concurrency)
        for task, result in results:
            if result.status != "scored" or result.score != 1.0:
                failures.append((task.task_id, result.status, result.score, result.gates))

    total = (
        sum(1 for split in ("dev", "frozen") for _ in (tasks_root / split).glob("*.yaml"))
        if tasks_root.exists()
        else 0
    )
    print(f"\nselftest --oracles: {total - len(failures)}/{total} oracles scored 1.0")
    if failures:
        print("FAILURES:")
        for task_id, status, score, gates in failures:
            print(f"  {task_id}: status={status} score={score}")
            for g in gates:
                if not g.passed:
                    print(f"    gate failed: {g.name} -- {g.reason}")
        return 1
    return 0


def _load_results_and_tasks(run_dir: Path, tasks_root: Path):
    from .report.run_log import RunLog

    log = RunLog(run_dir)
    results = log.read_all()
    if not results:
        raise SystemExit(f"{run_dir}: no results.jsonl, or it is empty")
    all_tasks = load_split(tasks_root, "dev") + load_split(tasks_root, "frozen")
    tasks_by_id = {t.task_id: t for t in all_tasks}
    return results, tasks_by_id


def cmd_report(args: argparse.Namespace) -> int:
    results, tasks_by_id = _load_results_and_tasks(Path(args.run_dir), Path(args.tasks_root))
    summary = summarize(tasks_by_id, results)

    scores_by_family: dict[str, list[float]] = {}
    for r in results:
        if r.status == "scored" and r.score is not None:
            task = tasks_by_id.get(r.task_id)
            family = task.family if task else "unknown"
            scores_by_family.setdefault(family, []).append(r.score)

    overall_ci = compute_overall_ci(scores_by_family, n_resamples=args.resamples)
    markdown = render_markdown(summary, overall_ci, title=f"orion-harness run: {args.run_dir}")
    print(markdown)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"\n(written to {args.out})", file=sys.stderr)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    run_a = Path(args.run_a)
    run_b = Path(args.run_b)
    from .report.run_log import RunLog

    results_a = {r.task_id: r.score for r in RunLog(run_a).read_all() if r.score is not None}
    results_b = {r.task_id: r.score for r in RunLog(run_b).read_all() if r.score is not None}

    try:
        ci = paired_delta_ci(results_a, results_b, n_resamples=args.resamples)
    except ValueError as e:
        print(f"orion-harness compare: {e}", file=sys.stderr)
        return 2

    n_common = len(set(results_a) & set(results_b))
    print(
        f"Delta (B - A) = {ci.point:.4f} [{ci.lo:.4f}, {ci.hi:.4f}] "
        f"(95% bootstrap CI, {ci.n_resamples} resamples, n={n_common} common tasks)"
    )
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    mde = minimum_detectable_effect(n=args.n, sd=args.sd, alpha=args.alpha, power=args.power)
    print(
        f"minimum detectable effect at n={args.n}, sd={args.sd}, "
        f"alpha={args.alpha}, power={args.power}: {mde:.4f}"
    )
    return 0


def cmd_tasks_lint(args: argparse.Namespace) -> int:
    report = lint_tasks_root(Path(args.tasks_root))
    print(f"orion-harness tasks lint: {report.n_tasks} tasks checked")
    if report.ok:
        print("clean")
        return 0
    for issue in report.issues:
        print(f"  {issue.task_id} ({issue.path}): {issue.message}")
    print(f"\n{len(report.issues)} issue(s)")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orion-harness")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser(
        "run", help="run oracle submissions over a split (no live model adapter wired up yet)"
    )
    p_run.add_argument("--tasks-root", default="tasks")
    p_run.add_argument("--oracles-root", default="oracles")
    p_run.add_argument("--split", default="dev", choices=["dev", "frozen", "held_out"])
    p_run.add_argument("--out", default=None)
    p_run.add_argument("--concurrency", type=int, default=2)
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify", help="score one submission against one task")
    p_verify.add_argument("--submission", required=True)
    p_verify.add_argument("--task", required=True)
    p_verify.add_argument("--model-id", default="manual")
    p_verify.set_defaults(func=cmd_verify)

    p_self = sub.add_parser("selftest", help="§13: assert oracles score 1.0")
    p_self.add_argument("--oracles", action="store_true")
    p_self.add_argument("--tasks-root", default="tasks")
    p_self.add_argument("--oracles-root", default="oracles")
    p_self.add_argument("--concurrency", type=int, default=2)
    p_self.set_defaults(func=cmd_selftest)

    p_report = sub.add_parser("report", help="render a run directory's results with CIs (R10)")
    p_report.add_argument("run_dir")
    p_report.add_argument("--tasks-root", default="tasks")
    p_report.add_argument("--resamples", type=int, default=10000)
    p_report.add_argument("--out", default=None, help="also write markdown to this path")
    p_report.set_defaults(func=cmd_report)

    p_compare = sub.add_parser("compare", help="paired-delta CI between two run directories")
    p_compare.add_argument("run_a")
    p_compare.add_argument("run_b")
    p_compare.add_argument("--resamples", type=int, default=10000)
    p_compare.set_defaults(func=cmd_compare)

    p_power = sub.add_parser("power", help="minimum detectable effect for a given suite size")
    p_power.add_argument("--n", type=int, required=True)
    p_power.add_argument("--sd", type=float, required=True)
    p_power.add_argument("--alpha", type=float, default=0.05)
    p_power.add_argument("--power", type=float, default=0.8)
    p_power.set_defaults(func=cmd_power)

    p_tasks = sub.add_parser("tasks")
    tasks_sub = p_tasks.add_subparsers(dest="tasks_command")
    p_lint = tasks_sub.add_parser("lint")
    p_lint.add_argument("--tasks-root", default="tasks")
    p_lint.set_defaults(func=cmd_tasks_lint)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
