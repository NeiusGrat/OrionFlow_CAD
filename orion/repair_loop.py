"""Diagnose a failed Blueprint and ask the model to fix it.

The corpus already contains 17,023 repair records shaped
``failure -> diagnosis -> fix -> re-verified``, but the SFT run trains only on
*verified* records, so the model has no learned recovery behaviour. This module
supplies that behaviour at the harness level: the verifier already knows exactly
what went wrong, so the diagnosis is derived, not guessed.

Two uses:

* **Demo** — a part fails, the machine explains *why* in engineering terms, the
  model corrects it, and the fix re-verifies. Live.
* **Metric** — ``VERIFIED @1 repair`` alongside raw ``VERIFIED``, which is the
  number that reflects how the system actually behaves in front of a user.

Diagnosis strings deliberately mirror the corpus ``repair_trace.diagnosis``
phrasing, so a model later trained on repair records sees a familiar prompt.
"""

from __future__ import annotations

from . import profiles as P

#: closed vocabularies — an out-of-grammar name is detectable before any build
VALID_BUILDERS = sorted(P.BUILDERS)


def diagnose(payload: dict | None, error: str, verdict: dict | None = None,
             measured: dict | None = None) -> str:
    """Turn a failure into an engineering explanation and a concrete instruction.

    ``error`` is the eval harness's classification (``parse:``, ``freeze:``,
    ``build:``, ``assert:``, ``precondition:``, ``timeout:``).

    ``measured`` is the raw measurement record from ``orion.measure_fc`` — the
    per-feature ``addsub_volume`` in it is what makes an ``assert`` failure
    actually repairable. Told only that a total is wrong, the model re-derives
    the same total and misses again; told which feature's own volume matches the
    discrepancy, it has somewhere to look. Passing it is optional so existing
    callers keep working, but an ``assert`` diagnosis without it is nearly
    contentless.
    """
    kind = (error or "").split(":", 1)[0].strip()
    detail = (error or "").split(":", 1)[-1].strip()

    if kind == "parse":
        return ("The response did not contain a single parseable JSON object. "
                "Emit the Blueprint as one JSON object after </think>, with no "
                "commentary after it.")

    if kind == "freeze":
        return (f"The Blueprint failed its static check: {detail}. Every "
                "dimension must be an expression over the named variables — a "
                "bare number in a feature parameter or sketch argument is "
                "rejected before anything is built.")

    if kind == "build":
        # The highest-value case: an invented builder is a closed-vocabulary
        # violation, so we can name the exact legal set.
        if "unknown profile builder" in detail:
            bad = detail.split("'")[1] if "'" in detail else "?"
            return (f"There is no sketch profile builder called '{bad}'. The "
                    f"available builders are: {', '.join(VALID_BUILDERS)}. "
                    "Compose the outline from one of those — a non-rectangular "
                    "plate outline is built with 'poly_with_holes', passing the "
                    "corner points explicitly as expressions.")
        return (f"The geometry kernel could not build the part: {detail}. "
                "Re-check that each feature's profile lies on the face it "
                "attaches to and that no cut extends past the material it "
                "removes from.")

    if kind == "precondition":
        # "choose better values" is useless without the arithmetic. Show the
        # expression, what it evaluated to, and the variables in play — a
        # violated guard is very often the right formula over the wrong
        # variable (a width guard written against the thickness, say), which is
        # only visible when the numbers are in front of you.
        failing = {i.strip() for i in detail.split(",") if i.strip()}
        exprs = {a.get("id"): a.get("target")
                 for a in (payload or {}).get("assertions", [])
                 if a.get("kind") == "precondition"}
        values = {p.get("id"): p.get("target")
                  for p in (verdict or {}).get("failed_preconditions", [])}
        lines = []
        for i in sorted(failing or values):
            e, v = exprs.get(i), values.get(i)
            lines.append(f"  {i}: {e} evaluated to "
                         f"{v if v is None else round(float(v), 4)} "
                         "— it must be greater than 0")
        body = "\n".join(lines)
        variables = (payload or {}).get("variables") or {}
        vs = ", ".join(f"{k}={v}" for k, v in sorted(variables.items()))
        return ("The part violates preconditions you authored, so the closed "
                f"form is not valid and nothing was built:\n{body}\n"
                f"Your variables are: {vs}\n"
                "Either the guard references the wrong variable (check that a "
                "width or length guard is not written against a thickness), or "
                "the values need to change. Fix whichever is actually wrong.")

    if kind == "assert":
        failed = [i for i in detail.split(",") if i]
        rows, deficit = [], None
        for a in (verdict or {}).get("assertions", []):
            if a.get("id") not in failed or a.get("measured") is None:
                continue
            target, got = a.get("target"), a.get("measured")
            rows.append(f"  {a['id']}: predicted {target}, measured {got}")
            if a.get("kind") == "body_volume" \
                    and isinstance(target, (int, float)) \
                    and isinstance(got, (int, float)):
                deficit = float(got) - float(target)
        body = ("\n" + "\n".join(rows)) if rows else ""

        # The per-feature tool volumes. This is the evidence that turns "the
        # total is wrong" into "this term is wrong": AddSubShape is each
        # feature's own solid before any boolean, so it is directly comparable
        # against the term the derivation wrote for it.
        feats = [f for f in (measured or {}).get("features", [])
                 if isinstance(f.get("addsub_volume"), (int, float))]
        table = ""
        if feats:
            table = ("\nWhat the kernel built, feature by feature (each "
                     "feature's own tool volume, before booleans):\n"
                     + "\n".join(
                         f"  {f.get('name')} "
                         f"({str(f.get('type_id', '')).split('::')[-1]}): "
                         f"{f['addsub_volume']:.4f}" for f in feats))

        # Match the discrepancy against those volumes. A miss that equals one
        # feature's volume is that feature counted the wrong number of times;
        # a miss smaller than any of them is usually an unaccounted overlap.
        hint = ""
        if deficit is not None and abs(deficit) > 1e-9:
            direction = "more" if deficit > 0 else "less"
            hint = (f"\nThe solid holds {abs(deficit):.4f} mm^3 {direction} "
                    f"material than your closed form predicts.")
            if feats:
                best = min(feats,
                           key=lambda f: abs(abs(deficit) - f["addsub_volume"]))
                off = abs(abs(deficit) - best["addsub_volume"]) \
                    / max(abs(deficit), 1e-12)
                if off < 0.02:
                    hint += (f" That is within 2% of {best.get('name')}'s own "
                             f"volume ({best['addsub_volume']:.4f}), so that "
                             f"feature's term is the one to re-derive — most "
                             f"likely counted the wrong number of times, or "
                             f"applied to material that was not there.")
                else:
                    hint += (" Compare it against the feature volumes above "
                             "to find which single term accounts for it.")

        notes = ""
        if payload:
            try:
                from .checker import advisories

                found = advisories(payload.get("variables") or {},
                                   payload.get("template") or {})
            except Exception:  # noqa: BLE001 — an advisory must never block repair
                found = []
            if found:
                notes = "\n" + "\n".join(f"Likely cause: {n}" for n in found)

        return (f"The part built, but the measured geometry disagrees with the "
                f"prediction for: {', '.join(failed)}.{body}{table}{hint}"
                f"{notes}\nThe feature tree is valid, so the derivation is "
                "what is wrong. Check whether a subtracted feature actually "
                "intersects the full extent you assumed (on a drafted or "
                "tapered body the section narrows with height, so a cut does "
                "not remove a full prism), and whether two features share "
                "volume that your sum counts twice.")

    if kind == "timeout":
        return ("The kernel did not converge on this geometry. Simplify the "
                "feature that is most likely to be self-intersecting.")

    return f"The part failed verification: {error}"


def build_repair_messages(original_messages: list[dict], bad_completion: str,
                          diagnosis: str) -> list[dict]:
    """The second-turn conversation: original ask, failed attempt, diagnosis.

    Kept as a real multi-turn exchange rather than a rewritten single prompt so
    the model sees its own output as its own — which is the shape the repair
    records use.
    """
    convo = [m for m in original_messages if m["role"] in ("system", "user")]
    convo.append({"role": "assistant", "content": bad_completion})
    convo.append({"role": "user", "content":
                  f"That part failed verification.\n\n{diagnosis}\n\n"
                  "Correct the Blueprint. Re-derive the volume if the "
                  "derivation was at fault, then emit the corrected Blueprint "
                  "as a single JSON object."})
    return convo
