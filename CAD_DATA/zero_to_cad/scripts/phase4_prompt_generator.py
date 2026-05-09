"""Phase 4: Generate engineering-style natural language prompts.

Reads  : analyzed/<split>.jsonl  (with structured 'features')
Writes : prompts/<split>.jsonl   (adds 'prompt' field, deterministic per uuid)

Five voices, deterministically chosen by hash(uuid) so re-runs are stable:
  spec_terse          - datasheet-style, ~1-2 sentences
  designer_brief      - conversational, like a Slack request
  manufacturing       - mentions material/tolerance hints
  functional_intent   - leads with what the part is FOR
  concise_oneliner    - <=20 words, dense
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYZED_DIR = ROOT / "analyzed"
OUT_DIR = ROOT / "prompts"

VOICES = ("spec_terse", "designer_brief", "manufacturing", "functional_intent", "concise_oneliner")


# ---------------------------------------------------------------------------
# Categorisation heuristics
# ---------------------------------------------------------------------------

def categorize(features: dict) -> str:
    """Best-effort part-category from features + dim names."""
    dims = features.get("dims", {})
    name_blob = " ".join(dims.keys()).lower()
    base = features.get("base_solid", "mixed")
    base_dims = features.get("base_dims") or []

    # Keyword-based first
    keywords = [
        ("bracket", ["bracket", "gusset", "mount_arm"]),
        ("housing", ["housing", "enclosure", "case", "shell"]),
        ("flange", ["flange"]),
        ("plate", ["plate"]),
        ("hub", ["hub", "spindle"]),
        ("shaft", ["shaft", "axle"]),
        ("bushing", ["bushing", "bearing"]),
        ("clamp", ["clamp", "yoke"]),
        ("manifold", ["manifold", "header", "port"]),
        ("fitting", ["fitting", "elbow", "tee_"]),
        ("cap", ["cap", "lid", "cover"]),
        ("base", ["base_plate", "baseplate"]),
        ("block", ["block"]),
    ]
    for label, kws in keywords:
        for kw in kws:
            if kw in name_blob:
                return label

    # Geometry-based fallback
    if base == "cylinder":
        return "cylindrical body"
    if base == "box":
        if len(base_dims) == 3:
            w, d, h = base_dims
            if h <= 0.25 * min(w, d):
                return "plate"
            if max(w, d) > 4 * min(w, d):
                return "bar"
            return "block"
        return "block"
    if base == "extrude":
        return "extruded profile"
    if base == "revolve":
        return "revolved body"
    if base == "sweep":
        return "swept body"
    return "part"


def _format_dim(v: float) -> str:
    if abs(v - round(v)) < 0.05:
        return f"{int(round(v))}"
    return f"{v:g}"


def _article(word: str) -> str:
    """Pick 'a' or 'an' based on the first sound of the next word."""
    if not word:
        return "a"
    first = word.lstrip().lower()[:1]
    return "an" if first in "aeiou" else "a"


def _sentence_case(text: str) -> str:
    """Capitalize first character only; preserve symbols like R, Ø."""
    text = text.lstrip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _holes_phrase(holes: dict, dims: dict) -> str | None:
    n_simple = holes.get("simple", 0)
    n_cbore = holes.get("cbore", 0)
    n_csk = holes.get("csk", 0)
    total = n_simple + n_cbore + n_csk
    if total == 0:
        return None

    # Try to find a hole-diameter dim
    diam_keys = [k for k in dims if "hole" in k.lower() and ("dia" in k.lower() or "diameter" in k.lower())]
    diam_str = ""
    if diam_keys:
        d = dims[diam_keys[0]]
        diam_str = f" Ø{_format_dim(d)}"  # diameter sign

    parts = []
    if n_simple:
        parts.append(f"{n_simple} through-hole{'s' if n_simple > 1 else ''}{diam_str}")
    if n_cbore:
        parts.append(f"{n_cbore} counterbored hole{'s' if n_cbore > 1 else ''}")
    if n_csk:
        parts.append(f"{n_csk} countersunk hole{'s' if n_csk > 1 else ''}")
    return ", ".join(parts)


def _edges_phrase(edges: dict) -> str | None:
    parts = []
    fillets = edges.get("fillet") or []
    chamfers = edges.get("chamfer") or []
    if fillets:
        r = fillets[0]
        if len(set(fillets)) == 1 and len(fillets) >= 1:
            parts.append(f"R{_format_dim(r)} fillet")
        else:
            parts.append(f"fillets ({', '.join(f'R{_format_dim(x)}' for x in fillets[:3])})")
    if chamfers:
        c = chamfers[0]
        if len(set(chamfers)) == 1:
            parts.append(f"{_format_dim(c)} mm chamfer")
        else:
            parts.append("multiple chamfers")
    return " and ".join(parts) if parts else None


def _pocket_phrase(features: dict) -> str | None:
    n = features.get("pockets", 0)
    if n == 0:
        return None
    dims = features.get("dims", {})
    pock_dims = {k: v for k, v in dims.items() if "pocket" in k.lower()}
    if pock_dims:
        keys = sorted(pock_dims.keys())
        if len(keys) >= 2:
            vals = [_format_dim(dims[k]) for k in keys[:3]]
            return f"a pocket measuring {' x '.join(vals)} mm"
    return f"{n} pocket{'s' if n > 1 else ''}"


_SIZE_HINT_KEYS = ("length", "width", "depth", "height", "thickness", "diameter", "size")


def _base_dim_phrase(features: dict, category: str) -> str:
    base = features.get("base_solid", "mixed")
    base_dims = features.get("base_dims") or []
    dims = features.get("dims", {})

    if base == "box" and len(base_dims) == 3:
        w, d, h = (_format_dim(x) for x in base_dims)
        return f"{w} x {d} x {h} mm"
    if base == "cylinder" and len(base_dims) >= 2:
        r, height = base_dims[0], base_dims[1]
        return f"Ø{_format_dim(2*r)} x {_format_dim(height)} mm"

    # Fallback: prefer dims whose name contains a size-hint keyword
    size_dims = [
        v for k, v in dims.items()
        if v > 0 and any(h in k.lower() for h in _SIZE_HINT_KEYS)
    ]
    vals = sorted(set(size_dims), reverse=True) or sorted(
        {v for v in dims.values() if v > 0}, reverse=True
    )
    if len(vals) >= 3:
        return f"approximately {_format_dim(vals[0])} x {_format_dim(vals[1])} x {_format_dim(vals[2])} mm"
    if len(vals) == 2:
        return f"approximately {_format_dim(vals[0])} x {_format_dim(vals[1])} mm"
    return ""


def _assemble_facts(features: dict, category: str) -> dict:
    return {
        "category": category,
        "dims_phrase": _base_dim_phrase(features, category),
        "holes": _holes_phrase(features.get("holes", {}), features.get("dims", {})),
        "edges": _edges_phrase(features.get("edges", {})),
        "pocket": _pocket_phrase(features),
        "extrusions": features.get("extrusions", 0),
        "revolutions": features.get("revolutions", 0),
        "multi_body": features.get("multi_body", False),
        "custom_profiles": features.get("custom_profiles", 0),
    }


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

def _join_clauses(clauses: list[str], rng: random.Random) -> str:
    clauses = [c for c in clauses if c]
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def voice_spec_terse(facts: dict, rng: random.Random) -> str:
    cat = facts["category"]
    art = _article(cat)
    lead = rng.choice([
        f"Design {art} {cat}",
        f"Model {art} {cat}",
        f"Create {art} {cat}",
        f"Generate {art} {cat}",
    ])
    if facts["dims_phrase"]:
        lead += f" measuring {facts['dims_phrase']}"
    details = []
    if facts["holes"]:
        details.append(facts["holes"])
    if facts["pocket"]:
        details.append(facts["pocket"])
    if facts["edges"]:
        details.append(facts["edges"])
    if facts["extrusions"] >= 1 and facts["multi_body"]:
        details.append(f"{facts['extrusions']} additional extruded feature{'s' if facts['extrusions'] > 1 else ''}")
    if facts["revolutions"] >= 1:
        details.append(f"{facts['revolutions']} revolved feature{'s' if facts['revolutions'] > 1 else ''}")

    body = _join_clauses(details, rng)
    if body:
        return f"{lead} with {body}."
    return f"{lead}."


def voice_designer_brief(facts: dict, rng: random.Random) -> str:
    cat = facts["category"]
    art = _article(cat)
    opener = rng.choice([
        f"I need {art} {cat}",
        f"Can you put together {art} {cat}",
        f"Looking for {art} {cat}",
        f"Need to model {art} {cat}",
    ])
    dims_phrase = facts["dims_phrase"]
    if dims_phrase:
        # Drop "approximately" when joined with "around"
        clean = dims_phrase.replace("approximately ", "")
        opener += f", around {clean}"
    items = []
    if facts["holes"]:
        items.append(f"it should have {facts['holes']}")
    if facts["pocket"]:
        items.append(f"add {facts['pocket']}")
    if facts["edges"]:
        items.append(f"break the edges with {_article(facts['edges'])} {facts['edges']}")
    if facts["multi_body"] and facts["extrusions"] >= 1:
        items.append("plus a couple of secondary features unioned to the main body")
    if facts["revolutions"]:
        items.append("with a revolved feature in the mix")
    body = ". ".join(_sentence_case(s) if i > 0 else s for i, s in enumerate(items))
    if body:
        return f"{opener}. {body}."
    return f"{opener}."


def voice_manufacturing(facts: dict, rng: random.Random) -> str:
    cat = facts["category"]
    material = rng.choice(["aluminum", "6061-T6 aluminum", "steel", "ABS", "Delrin"])
    process_hint = rng.choice([
        "for CNC milling",
        "intended for 3D printing",
        "machined from billet",
        "for prototyping",
    ])
    art = _article(material)
    lead = f"{_sentence_case(art)} {material} {cat} {process_hint}"
    if facts["dims_phrase"]:
        lead += f", overall {facts['dims_phrase']}"
    items = []
    if facts["holes"]:
        items.append(facts["holes"])
    if facts["pocket"]:
        items.append(facts["pocket"])
    if facts["edges"]:
        items.append(f"all sharp edges broken with {_article(facts['edges'])} {facts['edges']}")
    if facts["custom_profiles"]:
        items.append("a custom-profiled feature")
    body = _join_clauses(items, rng)
    if body:
        return f"{lead}. Required features: {body}."
    return f"{lead}."


def voice_functional_intent(facts: dict, rng: random.Random) -> str:
    cat = facts["category"]
    function = rng.choice([
        "for mounting an actuator",
        "for routing fasteners",
        "for clamping a shaft",
        "for joining two members",
        "for housing electronics",
        "for guiding a mechanism",
        "as a structural support",
    ])
    if "bracket" in cat or "gusset" in cat:
        function = rng.choice([
            "to support a vertical load",
            "to brace two perpendicular surfaces",
            "for mounting against a panel",
        ])
    art = _article(cat)
    lead = f"Design {art} {cat} {function}"
    if facts["dims_phrase"]:
        lead += f". Envelope {facts['dims_phrase']}"
    items = []
    if facts["holes"]:
        items.append(f"with {facts['holes']}")
    if facts["pocket"]:
        items.append(f"and {facts['pocket']}")
    if facts["edges"]:
        items.append(f"finished with {facts['edges']}")
    if items:
        return f"{lead}. " + _sentence_case(" ".join(items).strip()) + "."
    return f"{lead}."


def voice_concise_oneliner(facts: dict, rng: random.Random) -> str:
    parts = [facts["category"]]
    if facts["dims_phrase"]:
        parts.append(facts["dims_phrase"])
    bits = []
    if facts["holes"]:
        bits.append(facts["holes"])
    if facts["pocket"]:
        bits.append(facts["pocket"].replace("a pocket measuring", "pocket"))
    if facts["edges"]:
        bits.append(facts["edges"])
    if bits:
        parts.append(", ".join(bits))
    return ", ".join(parts).rstrip(".") + "."


VOICE_FNS = {
    "spec_terse": voice_spec_terse,
    "designer_brief": voice_designer_brief,
    "manufacturing": voice_manufacturing,
    "functional_intent": voice_functional_intent,
    "concise_oneliner": voice_concise_oneliner,
}


def generate_prompt(uuid: str, features: dict) -> tuple[str, str]:
    """Return (voice_name, prompt_text). Deterministic from uuid."""
    seed = int(hashlib.sha1(uuid.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    voice = rng.choice(VOICES)
    category = categorize(features)
    facts = _assemble_facts(features, category)
    text = VOICE_FNS[voice](facts, rng)
    # Tidy up double spaces and stray periods
    text = " ".join(text.split())
    text = text.replace(" .", ".").replace(" ,", ",").replace("..", ".")
    return voice, text


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = sys.argv[1:] or ["train", "validation", "test"]
    summary = {}
    for split in splits:
        in_path = ANALYZED_DIR / f"{split}.jsonl"
        if not in_path.exists():
            print(f"[{split}] missing {in_path}, skip")
            continue
        out_path = OUT_DIR / f"{split}.jsonl"
        n = 0
        voice_hist: dict[str, int] = {}
        with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                voice, prompt = generate_prompt(row["uuid"], row["features"])
                row["prompt"] = prompt
                row["prompt_voice"] = voice
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
                voice_hist[voice] = voice_hist.get(voice, 0) + 1
        summary[split] = {"count": n, "voices": voice_hist}
        print(f"[{split}] {n} rows -> {out_path}  voices={voice_hist}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
