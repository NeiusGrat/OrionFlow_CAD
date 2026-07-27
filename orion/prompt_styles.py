"""Many ways of asking for the same part.

The v1 model scored 91% on the packer's own prose shape and 50% on free-form
engineering language — the same parts, the same numbers, only the wording
changed. That is a language-generalisation failure, not a CAD failure, and it
comes from every training prompt sharing one skeleton::

    I need a {family}.
    It carries {attachments}.
    Dimensions (mm unless noted): {name} {value}, ...

This module renders a record in one of ~20 styles instead. No new geometry is
needed: the verified target is unchanged, only the request that produces it.

The variation that matters most is **terminology**, not sentence structure.
Real requests say "120 OD", "Ø40", "R12.5", "3 mm wall", "thk 8" — and above
all they give *diameters* where the blueprint stores *radii*. A model that has
only ever seen "bore radius 20" has no reason to connect it to "40 mm bore".
"""

from __future__ import annotations

import random

#: variables the corpus stores as radii — a request naming a diameter must be
#: halved to recover the stored value.
RADIUS_SUFFIXES = ("_r", "_hr", "_pr", "_br", "_cr", "_lr", "_sr", "_tr")
RADIUS_NAMES = ("r", "R", "rb", "bore_r", "hole_r", "flange_r", "barrel_r",
                "bc_r", "end_r", "pivot_r", "sec_r", "bend_r")


def is_radius(var: str) -> bool:
    return var in RADIUS_NAMES or var.endswith(RADIUS_SUFFIXES)


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# --------------------------------------------------------------------------- #
# how one dimension gets written
# --------------------------------------------------------------------------- #
def dim_phrases(var: str, value: float, prose: str, rng: random.Random) -> str:
    """One dimension, in one of several real-world spellings."""
    n = _num(value)
    forms = [f"{prose} {n}", f"{prose} of {n}", f"{prose}={n}",
             f"{prose} = {n}", f"{n} {prose}"]

    if is_radius(var):
        d = _num(value * 2)
        dia_word = prose.replace("radius", "diameter").replace("Radius", "diameter")
        if "diameter" not in dia_word:
            dia_word = dia_word + " diameter"
        forms += [f"{dia_word} {d}", f"{dia_word} of {d}", f"{d} {dia_word}",
                  f"Ø{d} {prose.replace(' radius', '').strip() or 'bore'}",
                  f"{d} mm {dia_word}", f"R{n} {prose.replace(' radius', '').strip()}"]
        if "bore" in prose:
            forms += [f"a {d} mm bore", f"bore for a {d} mm shaft",
                      f"{d} mm through bore"]

    low = prose.lower()
    if "thickness" in low:
        forms += [f"{n} thick", f"thk {n}", f"t={n}", f"{n} mm thick",
                  f"{n} mm wall" if "wall" in low else f"{n} thick"]
    if "length" in low:
        forms += [f"{n} long", f"L={n}", f"{n} mm long"]
    if "width" in low:
        forms += [f"{n} wide", f"W={n}", f"{n} mm wide"]
    if "height" in low:
        forms += [f"{n} tall", f"H={n}", f"{n} mm tall", f"{n} high"]
    if "count" in low or low.endswith(" n"):
        thing = prose.replace("count", "").replace("number of", "").strip() or "features"
        forms += [f"{n} {thing}", f"{n} off {thing}", f"{thing} x{n}"]
    if "angle" in low:
        forms += [f"{n} degrees", f"{n}°", f"drafted {n} degrees"]

    return rng.choice(forms)


# --------------------------------------------------------------------------- #
# how the whole request gets written
# --------------------------------------------------------------------------- #
OPENERS_SENTENCE = [
    "I need {a} {fam}.", "Design {a} {fam}.", "Create {a} {fam}.",
    "Build me {a} {fam}.", "Give me {a} {fam}.", "Model {a} {fam}.",
    "Can you make {a} {fam}?", "Could you design {a} {fam} for me?",
    "Please design {a} {fam}.", "I'm after {a} {fam}.",
    "We need {a} {fam} for a jig.", "Draw up {a} {fam}.",
    "Make {a} {fam}.", "I want {a} {fam}.",
]

TAILS = [
    "\nChoose sensible values for anything I have not given.",
    "\nPick reasonable values for whatever I've left out.",
    "\nFill in anything I haven't specified.",
    "\nUse your judgement for the rest.",
    "",
    "",
]

ASK = [
    "\nGive me the parametric feature tree with every dimension as an "
    "expression over named variables, and state the volume you expect and why.",
    "\nEverything must be parametric — expressions over named variables, no "
    "hard numbers in the feature tree.",
    "\nMake it fully parametric and tell me the expected volume.",
    "\nParametric please, and show your working for the volume.",
    "",
]


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _readable(name: str) -> str:
    return (name or "part").replace("_", " ").strip()


def render(family: str, attachments: list[str], dims: list[tuple[str, float, str]],
           rng: random.Random) -> str:
    """Render one request. ``dims`` is (var, value, prose_name)."""
    fam = _readable(family)
    style = rng.randrange(20)
    phr = [dim_phrases(v, val, prose, rng) for v, val, prose in dims]
    atts = [_readable(a) for a in attachments]

    def att_clause() -> str:
        if not atts:
            return ""
        j = atts[0] if len(atts) == 1 else \
            ", ".join(atts[:-1]) + f" and {atts[-1]}"
        return rng.choice([f" It carries {j}.", f" With {j}.",
                           f" It needs {j}.", f" Include {j}.",
                           f" Add {j}."])

    # --- terse / spec-sheet forms ---------------------------------------- #
    if style == 0:                                   # "flange, 120 OD, 14 thick"
        return f"{fam}, " + ", ".join(phr) + ("" if not atts else
                                              ", with " + ", ".join(atts))
    if style == 1:                                   # key: value block
        rows = "\n".join(f"  {p}" for p in phr)
        a = ("\n  attachments: " + ", ".join(atts)) if atts else ""
        return f"Part: {fam}\n{rows}{a}"
    if style == 2:                                   # bulleted requirements
        rows = "\n".join(f"- {p}" for p in phr)
        a = "\n" + "\n".join(f"- {x}" for x in atts) if atts else ""
        return f"Requirements for {_article(fam)} {fam}:\n{rows}{a}"
    if style == 3:                                   # manufacturing note
        return (f"Machined {fam} required. " + "; ".join(phr) + "."
                + att_clause())
    if style == 4:                                   # very short imperative
        return f"{rng.choice(['Design', 'Make', 'Build', 'Model'])} " \
               f"{_article(fam)} {fam}: " + ", ".join(phr) + "."

    # --- conversational / sentence forms --------------------------------- #
    opener = rng.choice(OPENERS_SENTENCE).format(a=_article(fam), fam=fam)
    body = rng.choice([
        " " + ", ".join(phr) + ".",
        " Dimensions: " + ", ".join(phr) + ".",
        " It should be " + ", ".join(phr) + ".",
        " Roughly " + ", ".join(phr) + ".",
        " Sizes are " + ", ".join(phr) + ".",
        "\nDimensions (mm unless noted): " + ", ".join(phr) + ".",
    ])
    return opener + att_clause() + body


def build_prompt(family: str, attachments: list[str],
                 dims: list[tuple[str, float, str]], rng: random.Random) -> str:
    """A complete user turn: the request, plus (usually) the standing asks."""
    return render(family, attachments, dims, rng) \
        + rng.choice(TAILS) + rng.choice(ASK)
