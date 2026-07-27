"""Pack the verified corpus into an SFT set whose target is a BUILDABLE Blueprint.

The Phase-5 RL pack (``forge_rl_pack.py``) emits reasoning, assertions and the
verification trace but *not* ``blueprint.template`` — a model trained on it can
derive a volume and never produce geometry. This packer targets the authored
contract itself::

    prompt  ->  <think> derivation + datums + predicted volume </think>
                {part_class, variables, datums, design_plan, assertions, template}

That JSON is precisely ``Blueprint.payload()`` minus ``version``, so a generated
sample round-trips through ``Blueprint.from_dict -> freeze -> resolve ->
reconstruct -> measure -> check`` with no recipe lookup anywhere. The model's
output is simultaneously the CAD and its own proof.

Two prompt views are emitted, one per record (deterministic by hash, ~50/50):

* **spec**   — every variable supplied, as in the RL pack. Teaches the exact
               template grammar.
* **design** — a prose engineering ask naming the family and its attachments,
               supplying only a subset of dimensions. The model must *choose*
               the rest. This is the view that survives a human typing at a
               live demo; the spec view alone does not.

Splits hold out whole ``topology_signature`` groups, never rows, so validation
measures generalisation to unseen topology rather than memorisation.

Usage::

    python -m orion.pack_sft \
        --db data/forge/corpus_v3_scale_frozen/corpus_v3_scale.db \
        --out data/forge/sft_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
from collections import Counter

SYSTEM_PROMPT = (
    "You are OrionFlow, a mechanical design engine. Given an engineering "
    "request you produce a parametric Blueprint: named variables, a feature "
    "tree in which every dimension is an expression over those variables "
    "(never a bare number), datums, and assertions that prove the result — "
    "including a closed-form body volume.\n"
    "Reason through the derivation inside <think>...</think>, then emit the "
    "Blueprint as a single JSON object and nothing else."
)

# --------------------------------------------------------------------------- #
# variable-name -> prose
# --------------------------------------------------------------------------- #
#: attachment sub-codes, as authored by orion/compose.py (att<N>_<code>)
ATT_CODES = {
    "cx": "centre x", "cy": "centre y", "cz": "centre z",
    "hr": "hole radius", "hd": "hole depth",
    "pr": "pin radius", "ph": "pin height",
    "br": "boss radius", "bh": "boss height",
    "cr": "counterbore radius", "cd": "counterbore depth",
    "sl": "slot length", "sr": "slot radius", "sw": "slot width",
    "rl": "rib length", "rw": "rib width", "rd": "rib depth",
    "rt": "rib thickness", "rh": "rib height",
    "lr": "lightening-pocket radius", "ld": "lightening-pocket depth",
    "tr": "thermal-relief radius", "td": "thermal-relief depth",
}

#: whole-name overrides for the recurring single-letter and stem variables
NAME_WORDS = {
    "L": "length", "W": "width", "H": "height", "R": "radius",
    "T": "thickness", "t": "thickness", "w": "width", "h": "height",
    "r": "radius", "d": "depth", "wall": "wall thickness",
    "ft": "flange thickness", "rb": "base radius",
}

#: stem words, applied to the leading token of a snake_case name
STEM_WORDS = {
    "bore": "bore", "flange": "flange", "barrel": "barrel", "hole": "hole",
    "floor": "floor", "roof": "roof", "web": "web", "rim": "rim",
    "hub": "hub", "boss": "boss", "pad": "pad", "lug": "lug",
    "shell": "shell", "stem": "stem", "span": "span", "end": "end",
    "base": "base", "top": "top", "leg": "leg", "arm": "arm",
    "fin": "fin", "slot": "slot", "rib": "rib", "pin": "pin",
    "neck": "neck", "throat": "throat", "cap": "cap", "seat": "seat",
}

#: trailing token -> measured quantity. Only applied to the tail of a
#: snake_case name; no variable in the corpus ends in ``_a``/``_ang``, so angle
#: is spelled out rather than abbreviated (a bare ``a`` is an arm length on the
#: lever families, and calling it an angle actively misleads the model).
TAIL_WORDS = {
    "r": "radius", "d": "diameter", "t": "thickness", "h": "height",
    "w": "width", "l": "length", "n": "count",
    "rad": "radius", "dia": "diameter", "th": "thickness",
    "len": "length", "angle": "angle", "cnt": "count", "num": "count",
}


def prose_name(var: str) -> str:
    """Human phrasing for a blueprint variable name ('flange_t' -> 'flange
    thickness'). Falls back to the raw name so unknown vocabulary is never
    silently mangled into something wrong."""
    if var in NAME_WORDS:
        return NAME_WORDS[var]
    parts = var.split("_")
    if parts[0].startswith("att") and parts[0][3:].isdigit() and len(parts) > 1:
        code = ATT_CODES.get(parts[-1])
        idx = int(parts[0][3:])
        ordinal = ("first", "second", "third", "fourth", "fifth")
        which = ordinal[idx] if idx < len(ordinal) else f"#{idx + 1}"
        return f"{which} feature {code}" if code else var
    if len(parts) >= 2:
        stem = STEM_WORDS.get(parts[0], parts[0])
        tail = TAIL_WORDS.get(parts[-1])
        if tail:
            return f"{stem} {tail}"
    # A bare single letter outside NAME_WORDS (``a``, ``b`` on the lever
    # families) is a family-specific dimension with no safe prose reading —
    # quote it verbatim, which is how a drawing would label it anyway.
    return var.replace("_", " ")


def _fmt(v: float) -> str:
    if isinstance(v, (int, float)) and float(v).is_integer():
        return str(int(v))
    return f"{v:g}"


def _readable(name: str) -> str:
    return name.replace("_", " ").strip()


# --------------------------------------------------------------------------- #
# prompt views
# --------------------------------------------------------------------------- #
def spec_prompt(rec: dict) -> str:
    """All variables supplied — the RL-pack phrasing, kept so the model still
    learns the template grammar under full specification."""
    bp = rec["blueprint"]
    lines = [f"Design a parametric {_readable(bp['part_class'])}."]
    plan = bp.get("design_plan", {})
    if plan.get("function"):
        lines.append(f"Function: {plan['function']}")
    if plan.get("manufacturing"):
        lines.append(f"Manufacturing: {plan['manufacturing']}")
    lines.append("Variables: " + ", ".join(
        f"{k}={_fmt(v)}" for k, v in sorted(bp["variables"].items())))
    lines.append("Every dimension must be an expression over the variables; "
                 "state the volume you expect and why.")
    return "\n".join(lines)


def design_prompt(rec: dict, rng: random.Random) -> str:
    """A prose engineering ask with only *some* dimensions pinned.

    The model must select the remaining variables itself and still satisfy the
    assertions it authors — which is exactly what a human typing at the demo
    forces it to do.
    """
    bp = rec["blueprint"]
    variables = bp["variables"]
    names = sorted(variables)
    # keep 40-70% of the dimensions; always keep at least one so the ask is
    # grounded in a real number rather than being pure invention.
    keep_n = max(1, int(round(len(names) * rng.uniform(0.40, 0.70))))
    # prefer keeping the non-attachment (primary envelope) variables
    primary = [n for n in names if not n.startswith("att")]
    secondary = [n for n in names if n.startswith("att")]
    rng.shuffle(primary)
    rng.shuffle(secondary)
    kept = (primary + secondary)[:keep_n]
    kept.sort(key=names.index)

    family = _readable(rec.get("base_family") or bp["part_class"])
    lines = [f"I need a {family}."]

    atts = rec.get("attachments") or []
    if atts:
        pretty = [_readable(a) for a in atts]
        joined = (pretty[0] if len(pretty) == 1
                  else ", ".join(pretty[:-1]) + f" and {pretty[-1]}")
        lines.append(f"It carries {joined}.")

    dims = ", ".join(f"{prose_name(k)} {_fmt(variables[k])}" for k in kept)
    lines.append(f"Dimensions (mm unless noted): {dims}.")

    missing = [n for n in names if n not in kept]
    if missing:
        lines.append("Choose sensible values for anything I have not given.")
    lines.append("Give me the parametric feature tree with every dimension as "
                 "an expression over named variables, and state the volume you "
                 "expect and why.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# target
# --------------------------------------------------------------------------- #
def think_block(rec: dict) -> str:
    """The derivation the engineer watches stream before geometry appears."""
    bp = rec["blueprint"]
    out = []
    for step in bp.get("design_plan", {}).get("derivation", []):
        eq = step.get("eq", "")
        why = step.get("why")
        out.append(f"{eq}" + (f"   — {why}" if why else ""))

    datums = bp.get("datums") or rec.get("datum_strategy") or {}
    if datums:
        out.append("Datums: " + "; ".join(
            f"{k} = {v}" for k, v in sorted(datums.items())))

    # the number the build is about to be checked against
    for a in rec.get("verdict", {}).get("assertions", []):
        if a.get("kind") == "body_volume" and a.get("target") is not None:
            out.append(f"Predicted volume: {a['target']:.4f} mm^3")
            break
    return "\n".join(out)


def target_json(rec: dict) -> dict:
    """Exactly ``Blueprint.payload()`` minus ``version`` — what the model emits
    and what ``Blueprint.from_dict`` consumes."""
    bp = rec["blueprint"]
    return {
        "part_class": bp["part_class"],
        "variables": bp["variables"],
        "datums": bp["datums"],
        "design_plan": bp["design_plan"],
        "assertions": bp["assertions"],
        "template": bp["template"],
    }


def diverse_prompt(rec: dict, rng: random.Random) -> str:
    """A request in one of ~20 real-world phrasings (see prompt_styles).

    v1 packed every design-view prompt with one skeleton and scored 91% on that
    shape against 50% on free engineering prose — same parts, same numbers.
    This view exists to close that gap without touching the geometry.
    """
    from .prompt_styles import build_prompt

    bp = rec["blueprint"]
    variables = bp["variables"]
    names = sorted(variables)
    keep_n = max(1, int(round(len(names) * rng.uniform(0.35, 0.75))))
    primary = [n for n in names if not n.startswith("att")]
    secondary = [n for n in names if n.startswith("att")]
    rng.shuffle(primary)
    rng.shuffle(secondary)
    kept = sorted((primary + secondary)[:keep_n], key=names.index)

    dims = [(k, variables[k], prose_name(k)) for k in kept]
    return build_prompt(rec.get("base_family") or bp["part_class"],
                        rec.get("attachments") or [], dims, rng)


def build_sample(rec: dict, view: str, rng: random.Random) -> dict:
    if view == "spec":
        prompt = spec_prompt(rec)
    elif view == "diverse":
        prompt = diverse_prompt(rec, rng)
    else:
        prompt = design_prompt(rec, rng)
    assistant = (f"<think>\n{think_block(rec)}\n</think>\n\n"
                 + json.dumps(target_json(rec)))
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ],
        "meta": {
            "blueprint_hash": rec["blueprint"].get("blueprint_hash", ""),
            "topology_signature": rec.get("_topology_signature"),
            "base_family": rec.get("base_family"),
            "part_class": rec["blueprint"]["part_class"],
            "view": view,
            "n_features": len(rec["blueprint"]["template"].get("features", [])),
        },
    }


# --------------------------------------------------------------------------- #
# corpus read + split
# --------------------------------------------------------------------------- #
def load_verified(db_path: str, limit: int | None = None) -> list[dict]:
    """Every record that BUILT and PASSED — the only rows whose template is
    known-good geometry."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = []
    try:
        sql = ("SELECT payload, topology_signature, base_family, attachments "
               "FROM records WHERE passed=1 AND payload IS NOT NULL")
        if limit:
            sql += f" LIMIT {int(limit)}"
        for payload, sig, fam, atts in con.execute(sql):
            try:
                rec = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            bp = rec.get("blueprint") or {}
            if not bp.get("template", {}).get("features"):
                continue          # no geometry to learn from
            rec["_topology_signature"] = sig
            if not rec.get("base_family"):
                rec["base_family"] = fam
            if not rec.get("attachments") and atts:
                try:
                    rec["attachments"] = json.loads(atts)
                except (TypeError, json.JSONDecodeError):
                    pass
            rows.append(rec)
    finally:
        con.close()
    return rows


def split_by_signature(rows: list[dict], val_frac: float, test_frac: float,
                       seed: int) -> dict[str, list[dict]]:
    """Hold out whole topology signatures. A row-wise split would put near
    identical parametrisations of one shape on both sides and report
    memorisation as generalisation."""
    sigs = sorted({r.get("_topology_signature") or r["blueprint"]["part_class"]
                   for r in rows})
    rng = random.Random(seed)
    rng.shuffle(sigs)
    n_val = max(1, int(len(sigs) * val_frac))
    n_test = max(1, int(len(sigs) * test_frac))
    val_sigs = set(sigs[:n_val])
    test_sigs = set(sigs[n_val:n_val + n_test])

    out = {"train": [], "val": [], "test": []}
    for r in rows:
        sig = r.get("_topology_signature") or r["blueprint"]["part_class"]
        key = "val" if sig in val_sigs else "test" if sig in test_sigs else "train"
        out[key].append(r)
    return out


def choose_view(rec: dict, design_frac: float,
                diverse_frac: float = 0.0) -> str:
    """Deterministic per-record view assignment: one view per record keeps the
    epoch the same size as the corpus while covering the distributions.

    ``diverse_frac`` takes priority — it is the view that teaches language
    robustness, and after v1 that is the scarce skill, not template grammar.
    """
    h = hashlib.sha256(
        (rec["blueprint"].get("blueprint_hash", "")
         + rec["blueprint"]["part_class"]).encode()).hexdigest()
    r = int(h[:8], 16) / 0xFFFFFFFF
    if r < diverse_frac:
        return "diverse"
    return "design" if r < diverse_frac + design_frac * (1 - diverse_frac) \
        else "spec"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-frac", type=float, default=0.04)
    ap.add_argument("--test-frac", type=float, default=0.04)
    ap.add_argument("--design-frac", type=float, default=0.5,
                    help="share of records packed as prose design asks")
    ap.add_argument("--diverse-frac", type=float, default=0.0,
                    help="share packed with randomised real-world phrasings")
    ap.add_argument("--seed", type=int, default=1602)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    rows = load_verified(args.db, args.limit)
    print(f"verified records with geometry: {len(rows)}")

    splits = split_by_signature(rows, args.val_frac, args.test_frac, args.seed)
    rng = random.Random(args.seed)
    stats: dict[str, Counter] = {}

    for name, recs in splits.items():
        path = os.path.join(args.out, f"{name}.jsonl")
        counter = Counter()
        lengths = []
        seen = set()
        written = 0
        with open(path, "w", encoding="utf-8") as fh:
            for rec in recs:
                view = choose_view(rec, args.design_frac, args.diverse_frac)
                sample = build_sample(rec, view, rng)
                key = hashlib.sha256(
                    (sample["messages"][1]["content"]
                     + sample["messages"][2]["content"]).encode()).hexdigest()
                if key in seen:
                    counter["dup_skipped"] += 1
                    continue
                seen.add(key)
                fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                written += 1
                counter[view] += 1
                counter[rec.get("base_family") or "?"] += 0
                lengths.append(sum(len(m["content"]) for m in sample["messages"]))
        counter["written"] = written
        stats[name] = counter
        lengths.sort()
        if lengths:
            p50 = lengths[len(lengths) // 2]
            p95 = lengths[int(len(lengths) * 0.95)]
            print(f"{name:>5}: {written:6d} samples  "
                  f"spec={counter['spec']} design={counter['design']} "
                  f"diverse={counter['diverse']}  "
                  f"chars p50={p50} p95={p95} max={lengths[-1]}")

    fams = Counter(r.get("base_family") for r in splits["train"])
    print(f"train families: {len(fams)}")
    print(f"held-out signatures: val={len({r['_topology_signature'] for r in splits['val']})} "
          f"test={len({r['_topology_signature'] for r in splits['test']})}")

    with open(os.path.join(args.out, "pack_stats.json"), "w",
              encoding="utf-8") as fh:
        json.dump({k: dict(v) for k, v in stats.items()}, fh, indent=1)


if __name__ == "__main__":
    main()
