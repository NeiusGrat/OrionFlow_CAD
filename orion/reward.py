"""Tiered verifiable reward — the signal an RL pass would optimise.

SFT cannot fix the model's remaining weakness. Every record in the corpus is a
*verified* one, so the model has never seen a bad dimension choice and its
consequence; unsurprisingly its live failures are preconditions it violated
itself and volumes it derived wrongly. RL generates its own negatives, which is
exactly the missing signal — and unlike most LLM RL, the reward here is a
deterministic verifier rather than a learned and gameable proxy.

The obstacle was always cost. Thousands of rollouts at 3 s of FreeCAD each is
hopeless. But most failures never need the kernel:

===========  =========================================  ==========  ==========
tier         checks                                     cost        catches
===========  =========================================  ==========  ==========
0  parse     one JSON object, required fields           ~0.1 ms     malformed
0  freeze    static check: no literal dimensions        ~1 ms       magic numbers
0  precond   every guard the model authored is > 0      ~1 ms       infeasible params
0  volume    closed form vs the profile builder's       ~1 ms       wrong derivation
             exact area, for extrusion-shaped trees
1  build     FreeCAD builds and measures                ~3000 ms    kernel truth
===========  =========================================  ==========  ==========

Tier 0 runs ~960x faster than a build and catches the classes that actually
dominate live failures, so it is the dense reward; Tier 1 is the periodic
ground-truth audit that keeps the cheap signal honest.

    from orion.reward import score
    r = score(completion)          # dense, no FreeCAD
    r = score(completion, build=True, workdir="...")   # + kernel truth
"""

from __future__ import annotations

from typing import Optional

from .blueprint import Blueprint, BlueprintError
from .eval_blueprint import extract_blueprint, to_blueprint

#: weights chosen so each stage is worth more than everything before it —
#: emitting parseable JSON should never out-score building a correct part.
WEIGHTS = {"parse": 0.10, "freeze": 0.20, "precond": 0.25,
           "volume": 0.45, "build": 1.00}


def analytic_volume(bp: Blueprint) -> Optional[float]:
    """Closed-form body volume from the profile builders, or None.

    Exact when the feature tree is a stack of additive extrusions whose
    profiles already carry their holes (the common case: one sketch, one Pad).
    Returns None when booleans between separately-sketched features make the
    result depend on overlaps the analytic path cannot see — those parts are
    left to the kernel rather than guessed at.
    """
    graph = bp.resolve()
    analysis = graph.get("_analysis") or {}
    by_sketch = {d["source"]: d["target"]
                 for d in bp.template.get("dependencies", [])
                 if d.get("kind") == "profile"}
    # Exactly ONE Pad, and nothing else that makes or removes material.
    #
    # An earlier version summed over every Pad assuming they were disjoint.
    # That is false whenever features stack or overlap, and it disagreed with
    # the kernel on 54% of real model outputs whose parts actually verify — a
    # reward wrong half the time would teach the model to satisfy a bug. Only
    # the single-extrusion case is unambiguous, because there the profile's own
    # area (holes already subtracted) times the length IS the solid.
    solid_types = [f["type"] for f in bp.template.get("features", [])
                   if f["type"] not in ("Body", "Sketch")]
    if solid_types != ["Pad"]:
        return None

    pads = [f for f in bp.template.get("features", []) if f["type"] == "Pad"]
    fid = pads[0]["id"]
    sids = [s for s, t in by_sketch.items() if t == fid]
    if len(sids) != 1 or sids[0] not in analysis:
        return None
    params = pads[0].get("parameters") or {}
    if params.get("Type") not in (None, "Length") or params.get("Midplane") \
            or params.get("Reversed") or params.get("Length2"):
        return None
    length = params.get("Length")
    if length is None:
        return None
    return analysis[sids[0]]["area"] * bp._num(length)


def score(completion: str, build: bool = False, workdir: str = ".",
          tag: str = "rl", tol: float = 1e-6) -> dict:
    """Grade one completion. Returns per-stage flags plus a scalar reward."""
    out = {"parse": False, "freeze": False, "precond": False,
           "volume": None, "build": None, "reward": 0.0, "error": None}

    try:
        payload = extract_blueprint(completion)
        out["parse"] = True
    except Exception as e:                       # noqa: BLE001
        out["error"] = f"parse: {str(e)[:120]}"
        return out

    try:
        bp = to_blueprint(payload)               # freeze() runs the static check
        out["freeze"] = True
    except (BlueprintError, Exception) as e:     # noqa: BLE001
        out["error"] = f"freeze: {str(e)[:160]}"
        out["reward"] = WEIGHTS["parse"]
        return out

    # ---- preconditions: pure arithmetic over the model's own guards ------- #
    try:
        bad = [a.get("id") for a in bp.resolve_assertions()
               if a.get("kind") == "precondition"
               and not (a.get("target_value") is not None
                        and a["target_value"] > 0)]
    except Exception as e:                       # noqa: BLE001
        out["error"] = f"precond: {str(e)[:120]}"
        out["reward"] = WEIGHTS["parse"] + WEIGHTS["freeze"]
        return out
    out["precond"] = not bad
    if bad:
        out["error"] = "precondition: " + ",".join(map(str, bad))

    reward = WEIGHTS["parse"] + WEIGHTS["freeze"]
    if out["precond"]:
        reward += WEIGHTS["precond"]

    # ---- analytic volume: does the authored closed form match the builder? - #
    try:
        predicted = None
        for a in bp.resolve_assertions():
            if a.get("kind") == "body_volume":
                predicted = a.get("target_value")
        exact = analytic_volume(bp)
        if predicted is not None and exact is not None:
            err = abs(predicted - exact) / max(abs(exact), 1e-12)
            out["volume"] = bool(err <= tol)
            out["volume_rel_err"] = err
            if out["volume"]:
                reward += WEIGHTS["volume"]
            elif not out["error"]:
                out["error"] = f"volume: closed form differs by {err:.2e}"
    except Exception:                            # noqa: BLE001
        out["volume"] = None                     # undecidable, not a failure

    # ---- kernel truth, only when asked ------------------------------------ #
    if build and out["precond"]:
        from . import forge
        try:
            v = forge.run_blueprint(bp, tag=tag, workdir=workdir)
            out["build"] = bool(v.get("passed"))
            if out["build"]:
                reward = WEIGHTS["build"]
            elif not out["error"]:
                out["error"] = "build: assertions failed"
        except Exception as e:                   # noqa: BLE001
            out["build"] = False
            out["error"] = f"build: {str(e)[:120]}"

    out["reward"] = round(min(reward, 1.0), 4)
    return out


def batch_score(completions: list[str], **kw) -> dict:
    """Aggregate stats over a rollout batch — what an RL loop logs each step."""
    rows = [score(c, **kw) for c in completions]
    n = max(len(rows), 1)
    decided = [r for r in rows if r["volume"] is not None]
    return {
        "n": len(rows),
        "mean_reward": round(sum(r["reward"] for r in rows) / n, 4),
        "parse": round(sum(r["parse"] for r in rows) / n, 4),
        "freeze": round(sum(r["freeze"] for r in rows) / n, 4),
        "precond": round(sum(r["precond"] for r in rows) / n, 4),
        "volume": (round(sum(bool(r["volume"]) for r in decided)
                         / max(len(decided), 1), 4) if decided else None),
        "volume_decidable": round(len(decided) / n, 4),
        "rows": rows,
    }
