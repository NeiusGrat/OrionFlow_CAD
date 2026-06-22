"""Run eval suites headless and print a scorecard.

Usage:
    python -m orion_agent.evals.run query        # real k2v2 think
    python -m orion_agent.evals.run query --mock  # offline, scripted LLM
    python -m orion_agent.evals.run all
"""

from __future__ import annotations

import sys

from orion_agent.harness.llm import get_llm_client
from orion_agent.evals.harness import EvalHarness


def _suite(name: str):
    if name == "query":
        from orion_agent.evals.query_suite import cases
        return cases()
    if name == "modify":
        from orion_agent.evals.modify_suite import cases
        return cases()
    raise SystemExit(f"unknown suite: {name}")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    suite_name = args[0] if args else "query"
    suites = ["query", "modify"] if suite_name == "all" else [suite_name]

    provider = "mock" if "--mock" in flags else "k2think"
    llm = get_llm_client(provider)
    harness = EvalHarness(llm)

    total_pass = total = 0
    grounded = accurate = honest = 0
    for sname in suites:
        cases = _suite(sname)
        print(f"\n=== {sname.upper()} SUITE ({len(cases)} cases, model={provider}) ===")
        results = harness.run_suite(cases)
        for r in results:
            total += 1
            total_pass += int(r.passed)
            grounded += int(r.grounded)
            accurate += int(r.accuracy)
            honest += int(r.no_hallucination)
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.name:18s} score={r.score:.2f} "
                  f"tools={r.tools_called}")
            if not r.passed:
                print(f"        {r.detail}")
                print(f"        answer: {r.answer[:160]}")

    print(f"\n--- TOTALS ---")
    print(f"passed:           {total_pass}/{total}")
    print(f"grounded:         {grounded}/{total}")
    print(f"numeric accuracy: {accurate}/{total}")
    print(f"no hallucination: {honest}/{total}")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
