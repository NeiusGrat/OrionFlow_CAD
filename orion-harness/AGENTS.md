# Working rules for agents in orion-harness

## Ground rules
- `src/orion_harness/contracts.py` is frozen after M0. Changing it requires a PR
  titled `contracts: ...` that updates every consumer in the same PR.
- One check has one implementation. If you are about to write a second version of a
  validator "just for the eval", stop and reuse the existing one.
- Every verifier has a `version` string. Changing behaviour without bumping it is a bug.
- Never run model-generated code in the harness process. Always subprocess, always
  a timeout, always a memory cap, never network.
- `score = None` for any status that is not "scored". Never use 0.0 as a sentinel for
  "did not run".
- Never trust a solver exit code. Validate outputs. See tests/test_solver_lies.py.
- Never hash raw STEP bytes for identity. Use geom_hash from execute/canonical.py.

## Before you open a PR
- `pytest` green, including `test_oracle_pass.py` and `test_mutations.py`.
- `orion-harness tasks lint` clean.
- If you added a check, you added: a task that passes it, a task that fails it, and a
  mutation test that proves it fails for the right reason.
- If you changed anything in `verify/` or `execute/`, paste before/after dev-split
  scores in the PR description.

## Do not
- Do not read individual tasks in tasks/frozen/ to debug. If you must, say so in the
  PR and move the task to dev.
- Do not touch tasks/held_out/.
- Do not add a dependency without pinning it and rebuilding the image digest.
- Do not add an LLM judge that outputs a number.
- Do not "improve" a score by relaxing a gate. Gates change only by explicit PR with
  engineering justification.

## When stuck
Write the failing case as a test first. If a task is ambiguous, the task is wrong —
fix the task, do not special-case the verifier.
