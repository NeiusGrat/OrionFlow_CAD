"""One prompt, end to end: ask the model, build it, prove it, export it.

This is the demo path in a single command — the same four beats a viewer sees:
derivation, geometry, verification against the model's own closed-form
prediction, and a file they can open.

    python -m orion.demo_once --prompt "I need an L bracket ..." --step

Add --repair to let a failure be diagnosed and retried once, which is the
fourth beat: the machine explains what is wrong in engineering terms and the
model corrects it.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

from .blueprint import Blueprint
from . import forge
from .eval_blueprint import extract_blueprint, to_blueprint
from .inspect_sample import export_step
from .repair_loop import build_repair_messages, diagnose

SYSTEM = (
    "You are OrionFlow, a mechanical design engine. Given an engineering "
    "request you produce a parametric Blueprint: named variables, a feature "
    "tree in which every dimension is an expression over those variables "
    "(never a bare number), datums, and assertions that prove the result — "
    "including a closed-form body volume.\n"
    "Reason through the derivation inside <think>...</think>, then emit the "
    "Blueprint as a single JSON object and nothing else."
)


def ask(endpoint: str, model: str, messages: list[dict], max_tokens: int,
        temperature: float) -> str:
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens,
                       "temperature": temperature}).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                 data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def show(completion: str) -> dict | None:
    """Render a completion. Returns None if no Blueprint could be parsed —
    a truncated generation is a normal failure mode, not a crash."""
    think, _, rest = completion.partition("</think>")
    try:
        payload = extract_blueprint(completion)
    except ValueError as e:
        print("\n--- DERIVATION ---")
        print(think.replace("<think>", "").strip()[:800])
        print(f"\n[no Blueprint parsed: {e}]")
        return None

    # The model reliably derives the volume *symbolically* and reliably fails to
    # evaluate it in prose: across 229 verified samples, the stated figure never
    # once matched its own assertion (errors up to 134%). Arithmetic in a single
    # forward pass is the weakest thing a transformer does. Its real prediction
    # is the expression, so show that evaluated — displaying the prose number
    # beside a passing assertion for a different value invites the obvious and
    # damning question.
    body = ""
    try:
        for a in to_blueprint(payload).resolve_assertions():
            if a.get("kind") == "body_volume":
                body = (f"Predicted volume (evaluated from the expression "
                        f"above): {a['target_value']:.4f} mm^3")
    except Exception:  # noqa: BLE001 — display only, never fail the demo here
        pass

    print("\n--- DERIVATION ---")
    for line in think.replace("<think>", "").strip().splitlines():
        if line.strip().startswith("Predicted volume:"):
            continue                      # model's own arithmetic, unreliable
        print(line)
    if body:
        print(body)

    t = payload.get("template", {})
    print("\n--- BLUEPRINT ---")
    print("part_class :", payload.get("part_class"))
    print("variables  :", json.dumps(payload.get("variables", {})))
    print("features   :", ", ".join(f"{f['id']}:{f['type']}"
                                    for f in t.get("features", [])))
    print("sketches   :", ", ".join(f"{s['id']}[{s['profile']['builder']}]"
                                    for s in t.get("sketches", [])))
    return payload


def verify(payload: dict, workdir: str, tag: str):
    bp = to_blueprint(payload)
    verdict = forge.run_blueprint(bp, tag=tag, workdir=workdir)
    print("\n--- VERIFICATION ---")
    print("  {:<20} {:<16} {:>15} {:>15} {:>10}".format(
        "assertion", "kind", "predicted", "measured", "rel_err"))
    for a in verdict.get("assertions", []):
        tgt, mea, rel = a.get("target"), a.get("measured"), a.get("rel_err")
        print("  {:<20} {:<16} {:>15} {:>15} {:>10}  {}".format(
            str(a.get("id"))[:20], str(a.get("kind"))[:16],
            f"{tgt:.4f}" if isinstance(tgt, float) else str(tgt),
            f"{mea:.4f}" if isinstance(mea, float) else "-",
            f"{rel:.2e}" if isinstance(rel, float) else "-",
            "PASS" if a.get("passed") else "FAIL"))
    for p in verdict.get("failed_preconditions", []):
        print(f"  precondition VIOLATED: {p.get('id')}")
    print("\nVERDICT:", "PASSED" if verdict.get("passed") else "FAILED")
    return bp, verdict


def classify(verdict: dict) -> str:
    """Same taxonomy the eval harness uses, so diagnoses line up."""
    if verdict.get("refused") or verdict.get("failed_preconditions"):
        ids = ",".join(str(p.get("id"))
                       for p in verdict.get("failed_preconditions", []))
        return f"precondition: {ids}"
    if not verdict.get("build_ok"):
        log = verdict.get("build_log", {}) or {}
        tail = (log.get("stderr") or "").strip().splitlines()
        return f"build: {tail[-1][:180] if tail else 'no output'}"
    bad = [a.get("id") for a in verdict.get("assertions", [])
           if not a.get("passed")]
    return "assert: " + ",".join(map(str, bad))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="orionflow")
    ap.add_argument("--out", default="builds/demo")
    ap.add_argument("--tag", default="demo")
    # A plate with a bore and four corner holes ran past 2560 and truncated
    # mid-JSON. Attachment-heavy parts need the headroom; the longest training
    # target was ~3000 tokens and the derivation sits on top of that.
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--step", action="store_true", help="also export STEP")
    ap.add_argument("--repair", action="store_true",
                    help="on failure, diagnose and retry once")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    workdir = os.path.abspath(args.out)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": args.prompt}]

    print("=" * 74)
    print("PROMPT:", args.prompt)
    print("=" * 74)
    t0 = time.time()
    completion = ask(args.endpoint, args.model, messages, args.max_tokens,
                     args.temperature)
    print(f"[generated in {time.time() - t0:.0f}s]")

    payload = show(completion)
    if payload is None:
        verdict = {"passed": False, "_parse_failed": True}
    else:
        bp, verdict = verify(payload, workdir, args.tag)

    if not verdict.get("passed") and args.repair:
        print("\n" + "=" * 74)
        print("REPAIR — the verifier knows what went wrong; ask for a fix")
        print("=" * 74)
        kind = ("parse: truncated or malformed JSON"
                if verdict.get("_parse_failed") else classify(verdict))
        d = diagnose(payload, kind, verdict)
        print("DIAGNOSIS:", d)
        t0 = time.time()
        fixed = ask(args.endpoint, args.model,
                    build_repair_messages(messages, completion, d),
                    args.max_tokens, args.temperature)
        print(f"[repaired in {time.time() - t0:.0f}s]")
        payload = show(fixed)
        if payload is not None:
            bp, verdict = verify(payload, workdir, args.tag + "_repaired")

    fcstd = os.path.join(workdir, f"{args.tag}.FCStd")
    if verdict.get("passed") and os.path.exists(fcstd):
        print(f"\nopen in FreeCAD:\n  {fcstd}")
        if args.step:
            step = os.path.join(workdir, f"{args.tag}.step")
            if export_step(fcstd, step):
                print(f"STEP:\n  {step}")


if __name__ == "__main__":
    main()
