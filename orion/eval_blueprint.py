"""Score generated Blueprints by BUILDING them — the only metric that counts.

Token-level loss says nothing about whether a part exists. This harness takes
model completions, parses the Blueprint out of them, and runs the identical
path the forge uses::

    completion -> json -> Blueprint.freeze()   (static check: no magic numbers)
               -> resolve() -> reconstruct.py -> FreeCAD -> measure
               -> check_assertions()           (against the model's OWN targets)

and reports the funnel. ``verified`` is the headline: the model authored a
parametric part, predicted its volume in closed form, and the kernel agreed.

Generation and verification are decoupled on purpose — completions are produced
wherever the GPU is and scored wherever FreeCAD is.

Verify a completions file::

    python -m orion.eval_blueprint --completions runs/ckpt3.jsonl

Generate against an OpenAI-compatible server (vLLM), then verify::

    python -m orion.eval_blueprint --data data/forge/sft_v1/val.jsonl \
        --endpoint http://localhost:8000/v1 --model orionflow --n 200

Sanity-check the harness itself against the reference targets (expect ~100%)::

    python -m orion.eval_blueprint --data data/forge/sft_v1/val.jsonl --gold --n 50
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from .blueprint import Blueprint, BlueprintError
from . import forge

_print_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def extract_blueprint(completion: str) -> dict:
    """Pull the Blueprint object out of a completion.

    Tolerates the think block, an optional ```json fence, and trailing prose —
    a real sampled completion is not guaranteed to be tidy. Raises ValueError
    if no balanced JSON object is present.
    """
    text = completion
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    if "```" in text:
        # take the first fenced block, stripping an optional language tag
        chunk = text.split("```", 2)[1]
        text = chunk.split("\n", 1)[1] if chunk.lstrip().startswith("json") \
            else chunk
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in completion")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON object in completion")


ALLOWED = {"part_class", "variables", "datums", "design_plan",
           "assertions", "template"}


def to_blueprint(payload: dict) -> Blueprint:
    """Frozen Blueprint from a parsed payload; drops keys the model may have
    hallucinated (``version``/``blueprint_hash`` are ours to set, not its)."""
    clean = {k: v for k, v in payload.items() if k in ALLOWED}
    missing = ALLOWED - set(clean)
    if missing:
        raise BlueprintError(f"missing fields: {sorted(missing)}")
    return Blueprint(**clean).freeze()


# --------------------------------------------------------------------------- #
# one sample through the whole funnel
# --------------------------------------------------------------------------- #
def score_one(idx: int, completion: str, meta: dict, workdir: str,
              verbose: bool = False) -> dict:
    out = {"idx": idx, "view": meta.get("view"),
           "base_family": meta.get("base_family"),
           "parse_ok": False, "freeze_ok": False, "refused": False,
           "build_ok": False, "verified": False,
           "vol_rel_err": None, "error": None}
    try:
        payload = extract_blueprint(completion)
        out["parse_ok"] = True
    except Exception as e:                        # malformed sample
        out["error"] = f"parse: {e}"
        return out
    try:
        bp = to_blueprint(payload)
        out["freeze_ok"] = True                   # passed the no-literals check
    except Exception as e:
        out["error"] = f"freeze: {str(e)[:160]}"
        return out
    try:
        verdict = forge.run_blueprint(bp, tag=f"eval_{idx}", workdir=workdir)
    except Exception as e:
        out["error"] = f"build: {str(e)[:160]}"
        return out

    out["refused"] = bool(verdict.get("refused"))
    out["build_ok"] = bool(verdict.get("build_ok"))
    out["verified"] = bool(verdict.get("passed"))
    out["part_class"] = bp.part_class

    # A build that produced no measurement is an infrastructure event as often
    # as it is a bad part (OCC wedging, a starved worker hitting the wall
    # clock). Keep the kernel's own words — attributing a timeout to the model
    # understates its score and sends you debugging the wrong thing.
    if not out["build_ok"] and not out["refused"]:
        log = verdict.get("build_log", {}) or {}
        if log.get("timeout"):
            out["error"] = "timeout: kernel exceeded the build budget"
            out["timeout"] = True
        else:
            tail = (log.get("stderr") or log.get("stdout") or "").strip()
            last = tail.splitlines()[-1][:180] if tail else "no output"
            out["error"] = f"build: rc={log.get('returncode')} {last}"
        return out
    for a in verdict.get("assertions", []):
        if a.get("kind") == "body_volume":
            out["vol_rel_err"] = a.get("rel_err")
            break
    if not out["verified"] and not out["error"]:
        bad = [a.get("id") for a in verdict.get("assertions", [])
               if not a.get("passed")]
        pre = [p.get("id") for p in verdict.get("failed_preconditions", [])]
        out["error"] = ("precondition: " + ",".join(map(str, pre))) if pre \
            else ("assert: " + ",".join(map(str, bad)) if bad else "no assertions")
    if verbose:
        with _print_lock:
            flag = "OK " if out["verified"] else "FAIL"
            print(f"  [{flag}] {idx:4d} {out.get('part_class','?')[:38]:38s} "
                  f"{out['error'] or ''}")
    return out


# --------------------------------------------------------------------------- #
# generation (optional)
# --------------------------------------------------------------------------- #
def generate(rows: list[dict], endpoint: str, model: str, max_tokens: int,
             temperature: float, workers: int) -> list[str]:
    """Sample completions from an OpenAI-compatible server (vLLM)."""
    import os
    import urllib.request

    # A local vLLM accepts any bearer token, but a served endpoint on a public
    # IP must not — so take the real key from the environment when there is
    # one and fall back to the placeholder for the unauthenticated local case.
    api_key = os.environ.get("ORION_LLM_API_KEY") or "EMPTY"

    def one(row: dict) -> str:
        msgs = row.get("repair_messages") or \
            [m for m in row["messages"] if m["role"] != "assistant"]
        body = json.dumps({"model": model, "messages": msgs,
                           "max_tokens": max_tokens,
                           "temperature": temperature}).encode()
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, rows))


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", help="packed jsonl (val/test) with messages+meta")
    ap.add_argument("--completions", help="jsonl of {completion, meta}")
    ap.add_argument("--endpoint", help="OpenAI-compatible base url, e.g. .../v1")
    ap.add_argument("--model", default="orionflow")
    ap.add_argument("--gold", action="store_true",
                    help="score the reference targets (harness sanity check)")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--gen-workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=3072)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--out", help="write per-sample results here")
    ap.add_argument("--repair-endpoint",
                    help="OpenAI-compatible url; retry each failure once with "
                         "a diagnosis and report VERIFIED @1 repair")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # ---- assemble (completion, meta) pairs -------------------------------- #
    def _meta(row: dict) -> dict:
        """Carry the originating turns inside meta so a repair round can show
        the model its own attempt in context."""
        m = dict(row.get("meta") or {})
        if row.get("messages"):
            m["_messages"] = row["messages"]
        return m

    if args.completions:
        rows = [json.loads(ln) for ln in open(args.completions, encoding="utf-8")]
        pairs = [(r["completion"], _meta(r)) for r in rows][:args.n]
    else:
        if not args.data:
            ap.error("need --data or --completions")
        data = [json.loads(ln) for ln in open(args.data, encoding="utf-8")][:args.n]
        for r in data:      # packed rows carry the full 3-turn conversation
            r.setdefault("meta", {})
            r["meta"]["_messages"] = [m for m in r["messages"]
                                      if m["role"] != "assistant"]
        if args.gold:
            pairs = [(r["messages"][2]["content"], r["meta"]) for r in data]
        else:
            if not args.endpoint:
                ap.error("need --endpoint to generate, or pass --gold")
            print(f"generating {len(data)} completions from {args.endpoint} ...")
            comps = generate(data, args.endpoint, args.model, args.max_tokens,
                             args.temperature, args.gen_workers)
            pairs = list(zip(comps, [r["meta"] for r in data]))
            if args.out:
                with open(args.out + ".completions.jsonl", "w",
                          encoding="utf-8") as fh:
                    for c, m in pairs:
                        fh.write(json.dumps({"completion": c, "meta": m}) + "\n")

    # ---- verify ----------------------------------------------------------- #
    workdir = tempfile.mkdtemp(prefix="orion_eval_")
    print(f"verifying {len(pairs)} completions in {workdir} "
          f"({args.workers} workers)")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(
            lambda t: score_one(t[0], t[1][0], t[1][1], workdir, args.verbose),
            enumerate(pairs)))

    # ---- report ----------------------------------------------------------- #
    n = len(results)
    def pct(key): return 100.0 * sum(bool(r[key]) for r in results) / max(n, 1)

    print("\n" + "=" * 58)
    print(f"  samples            {n}")
    print(f"  parsed JSON        {pct('parse_ok'):6.1f}%")
    print(f"  froze (no magic #) {pct('freeze_ok'):6.1f}%")
    print(f"  built in FreeCAD   {pct('build_ok'):6.1f}%")
    print(f"  VERIFIED           {pct('verified'):6.1f}%   <- headline")
    print(f"  refused (precond)  {pct('refused'):6.1f}%")

    errs = [r["vol_rel_err"] for r in results
            if r["verified"] and r["vol_rel_err"] is not None]
    if errs:
        print(f"  volume rel_err     median={statistics.median(errs):.2e} "
              f"max={max(errs):.2e}  (n={len(errs)})")

    for view in ("spec", "design"):
        sub = [r for r in results if r["view"] == view]
        if sub:
            v = 100.0 * sum(r["verified"] for r in sub) / len(sub)
            print(f"  view={view:<7s}      {v:6.1f}%  (n={len(sub)})")

    # ---- optional repair round ------------------------------------------- #
    # The corpus trains only on verified records, so the model has no learned
    # recovery behaviour; the verifier, however, knows exactly what went wrong.
    # One diagnosed retry is what the system actually does in front of a user,
    # so report that number next to the raw one.
    if args.repair_endpoint:
        from .repair_loop import build_repair_messages, diagnose
        broken = [(i, r) for i, r in enumerate(results) if not r["verified"]]
        retryable = [(i, r) for i, r in broken
                     if len(pairs[i]) > 1 and pairs[i][1].get("_messages")]
        print(f"\nrepair round: {len(retryable)} of {len(broken)} failures "
              "have their originating prompt")
        if retryable:
            reqs = []
            for i, r in retryable:
                meta = pairs[i][1]
                reqs.append({"repair_messages": build_repair_messages(
                    meta["_messages"], pairs[i][0],
                    diagnose(None, r["error"] or ""))})
            fixed = generate(reqs, args.repair_endpoint, args.model,
                             args.max_tokens, args.temperature,
                             args.gen_workers)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                rescored = list(pool.map(
                    lambda t: score_one(10000 + t[0][0], t[1],
                                        pairs[t[0][0]][1], workdir),
                    zip(retryable, fixed)))
            for (i, _), new in zip(retryable, rescored):
                if new["verified"]:
                    results[i] = {**new, "repaired": True}
            n_fixed = sum(1 for r in rescored if r["verified"])
            print(f"  repaired {n_fixed}/{len(retryable)}")
            print(f"  VERIFIED @1 repair {pct('verified'):6.1f}%")

    fails = {}
    for r in results:
        if not r["verified"] and r["error"]:
            fails[r["error"].split(":")[0]] = fails.get(
                r["error"].split(":")[0], 0) + 1
    if fails:
        print("  failure modes:     " + ", ".join(
            f"{k}={v}" for k, v in sorted(fails.items(), key=lambda x: -x[1])))
    print("=" * 58)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"n": n,
                       "verified_pct": pct("verified"),
                       "build_pct": pct("build_ok"),
                       "parse_pct": pct("parse_ok"),
                       "results": results}, fh, indent=1)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
