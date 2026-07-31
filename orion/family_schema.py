"""What each part family's variables actually are, mined from the training set.

An orchestration layer that plans a part has to name its variables, and the only
names that mean anything are the ones the adapter saw paired with that family.
``mount_plate`` is ``hr, mx, my, pl, pt, pw``. ``wheel_hub`` is ``barrel_h,
barrel_r, bc_r, bore_r, flange_r, flange_t, hole_n, hole_r``. Neither is
guessable — plausible substitutes like ``L, W, t`` are simply a different
distribution, and a planner that invents them puts the model off the data its
95% was measured on, one layer above where anyone will look for the cause.

So this is not documentation. It is the schema a planner fills in, derived from
the corpus rather than written down beside it, which means it cannot drift from
what the model was actually trained on.

Measured on ``sft_v1``: every family's base variable set is present in **100%**
of its samples. The schema is exact, not statistical. Ranges are observational —
they say where verified parts have lived, which is the region a planner should
stay inside unless it has a reason not to.

Regenerate after any corpus change::

    python -m orion.family_schema --data data/forge/sft_v1/train.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Optional

DEFAULT_DATA = os.path.join("data", "forge", "sft_v1", "train.jsonl")

#: Ships with the code, not with the corpus. ``data/`` is gitignored — sensibly,
#: it holds tens of thousands of parts — so an artifact left there would be
#: absent on a clean checkout, ``for_family`` would return None for every
#: family, and the whole layer would be silently inert. It is 69 KB and it is a
#: runtime dependency, so it lives beside the module that reads it.
DEFAULT_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "schema", "family_schema.json")

#: Guards that composition adds to every attachment, not authored by the family.
#: Listed separately so a family's own engineering guards stay visible.
_COMPOSED_GUARD_MARKERS = ("_in_land_", "_clear_att", "_ring")

#: What a sketch builder's argument measures. Roles are mined rather than
#: written down because a third of the corpus variables have names no prose
#: layer can read — ``mount_plate`` is ``hr, mx, my, pl, pt, pw``, and
#: ``pack_sft.prose_name`` falls straight through on all six. The template does
#: know what they mean: ``pl`` is the base rect's ``w``, ``pt`` is the Pad's
#: ``Length``, ``hr`` is the radius slot of every hole tuple. Reading the role
#: off the feature tree turns an opaque name into something a planner can be
#: asked for in English.
_ARG_ROLE = {
    "cx": "centre x", "cy": "centre y",
    "r": "radius", "radius": "radius", "r_circum": "circumscribed radius",
    "r_outer": "outer radius", "r_inner": "inner radius",
    "r_bc": "bolt-circle radius", "r_hole": "hole radius",
    "w": "length (X)", "h": "width (Y)", "length": "length",
    "n": "count", "nx": "count (X)", "ny": "count (Y)",
    "pitch_x": "pitch (X)", "pitch_y": "pitch (Y)",
    "start_deg": "start angle", "sweep_deg": "sweep angle",
}

#: Positional roles inside the list-valued builder arguments.
_LIST_ARG_ROLE = {
    "holes": ("hole centre x", "hole centre y", "hole radius"),
    "points": ("outline x", "outline y"),
}

#: What a feature parameter measures, by feature type.
_PARAM_ROLE = {
    ("Pad", "Length"): "extrude depth",
    ("Pocket", "Length"): "cut depth",
    ("Pocket", "Length2"): "second-side cut depth",
    ("Revolution", "Angle"): "revolve angle",
    ("Groove", "Angle"): "groove angle",
    ("Draft", "Angle"): "draft angle",
    ("PolarPattern", "Occurrences"): "instance count",
    ("PolarPattern", "Angle"): "pattern angle",
    ("LinearPattern", "Occurrences"): "instance count",
    ("LinearPattern", "Length"): "pattern span",
    ("Thickness", "Value"): "wall thickness",
    ("Fillet", "Radius"): "fillet radius",
    ("Chamfer", "Size"): "chamfer size",
}


@dataclass
class VariableStat:
    name: str
    count: int = 0
    always: bool = True
    integral: bool = True          # every observed value was a whole number
    lo: float = 0.0
    hi: float = 0.0
    median: float = 0.0
    role: str = ""                 # what the template uses it as

    def describe(self) -> str:
        fmt = "{:g}"
        span = (f"{fmt.format(self.lo)}..{fmt.format(self.hi)}"
                if self.lo != self.hi else fmt.format(self.lo))
        kind = "int" if self.integral else "float"
        opt = "" if self.always else ", optional"
        role = f"{self.role}, " if self.role else ""
        return (f"{self.name} ({role}{kind}, {span}, "
                f"typical {fmt.format(self.median)}{opt})")


@dataclass
class FamilySchema:
    family: str
    n_samples: int = 0
    variables: dict[str, VariableStat] = field(default_factory=dict)
    #: guards the family itself authors — the engineering constraints a planner
    #: must satisfy or have the part refused before it is ever built
    preconditions: dict[str, str] = field(default_factory=dict)
    #: attachment kinds observed on this family
    attachments: list[str] = field(default_factory=list)

    def required(self) -> list[str]:
        return sorted(n for n, v in self.variables.items() if v.always)

    def describe(self) -> str:
        """A block a planner can be shown. Compact, exact, no prose padding."""
        lines = [f"{self.family} (n={self.n_samples})", "  variables:"]
        lines += [f"    {self.variables[n].describe()}"
                  for n in sorted(self.variables)]
        if self.preconditions:
            lines.append("  must hold (each expression must be > 0):")
            lines += [f"    {k}: {v}" for k, v in sorted(self.preconditions.items())]
        if self.attachments:
            lines.append("  attachments seen: " + ", ".join(self.attachments))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["variables"] = {k: asdict(v) for k, v in self.variables.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FamilySchema":
        variables = {k: VariableStat(**v) for k, v in (d.get("variables") or {}).items()}
        return cls(family=d["family"], n_samples=d.get("n_samples", 0),
                   variables=variables,
                   preconditions=d.get("preconditions") or {},
                   attachments=d.get("attachments") or [])


# --------------------------------------------------------------------------- #
# mining
# --------------------------------------------------------------------------- #
def _attachment_kind(prefix: str, variables: dict) -> Optional[str]:
    from .checker import _attachment_footprint

    got = _attachment_footprint(prefix, variables)
    return got[0] if got else None


def _prose_role(name: str) -> str:
    """``pack_sft``'s reading of a variable name, or "" if it has none.

    ``prose_name`` returns the raw name (underscores spaced) when it cannot read
    a variable, so that is the sentinel for "no prose meaning".
    """
    from .pack_sft import prose_name

    reading = prose_name(name)
    return "" if reading == name.replace("_", " ") else reading


def _roles_in(template: dict) -> dict[str, str]:
    """Variable -> role, read off one feature tree.

    Only a *bare* reference counts: ``{"w": "pl"}`` says ``pl`` is the length,
    but ``{"Length": "att0_bh + (pt) + 2"}`` says nothing clean about either
    name. Attributing a role through arithmetic would produce confident
    nonsense, and a missing role is a much cheaper mistake than a wrong one.
    """
    found: dict[str, str] = {}

    def claim(value, role: str) -> None:
        if isinstance(value, str) and value.strip().isidentifier():
            found.setdefault(value.strip(), role)

    for sketch in template.get("sketches") or []:
        args = ((sketch.get("profile") or {}).get("args") or {})
        for arg, value in args.items():
            if arg in _LIST_ARG_ROLE and isinstance(value, list):
                slots = _LIST_ARG_ROLE[arg]
                for item in value:
                    if not isinstance(item, (list, tuple)):
                        continue
                    for i, entry in enumerate(item[:len(slots)]):
                        claim(entry, slots[i])
            elif arg in _ARG_ROLE:
                claim(value, _ARG_ROLE[arg])

    for feature in template.get("features") or []:
        ftype = feature.get("type")
        for param, value in (feature.get("parameters") or {}).items():
            role = _PARAM_ROLE.get((ftype, param))
            if role:
                claim(value, role)
    return found


def mine(data_path: str = DEFAULT_DATA,
         limit: Optional[int] = None) -> dict[str, FamilySchema]:
    """Build the schema by reading the packed training set.

    Only the ``spec`` view is read. It states every variable explicitly, so the
    variable set it implies is exactly what the model was conditioned on — a
    prose view mentions a subset and would understate the schema.
    """
    seen: dict[str, dict[str, list[float]]] = {}
    counts: dict[str, int] = {}
    guards: dict[str, dict[str, str]] = {}
    atts: dict[str, set] = {}
    roles: dict[str, dict[str, collections.Counter]] = {}

    with open(data_path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            rec = json.loads(line)
            meta = rec.get("meta") or {}
            family = meta.get("base_family")
            if not family or meta.get("view") != "spec":
                continue
            try:
                blueprint = json.loads(
                    rec["messages"][2]["content"].split("</think>")[1].strip())
            except (IndexError, ValueError):
                continue

            variables = blueprint.get("variables") or {}
            counts[family] = counts.get(family, 0) + 1
            bucket = seen.setdefault(family, {})
            for name, value in variables.items():
                if name.startswith("att"):
                    kind = _attachment_kind(name.split("_")[0], variables)
                    if kind:
                        atts.setdefault(family, set()).add(kind)
                    continue          # attachment vars are composed, not authored
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bucket.setdefault(name, []).append(float(value))

            # Roles are voted on across samples: a family's template is stable,
            # so this converges immediately, but a majority is still safer than
            # trusting whichever sample happened to be read first.
            fam_roles = roles.setdefault(family, {})
            for name, role in _roles_in(blueprint.get("template") or {}).items():
                if not name.startswith("att"):
                    fam_roles.setdefault(name, collections.Counter())[role] += 1

            g = guards.setdefault(family, {})
            for a in blueprint.get("assertions") or []:
                aid = str(a.get("id", ""))
                if a.get("kind") != "precondition":
                    continue
                if any(mark in aid for mark in _COMPOSED_GUARD_MARKERS):
                    continue
                g.setdefault(aid, str(a.get("target", "")))

    out: dict[str, FamilySchema] = {}
    for family, bucket in seen.items():
        n = counts[family]
        schema = FamilySchema(family=family, n_samples=n,
                              preconditions=guards.get(family, {}),
                              attachments=sorted(atts.get(family, ())))
        fam_roles = roles.get(family, {})
        for name, values in bucket.items():
            votes = fam_roles.get(name)
            if not votes:
                # No bare reference anywhere — the variable is only ever used
                # inside arithmetic. The name itself may still be readable
                # (``wall``, ``floor_t``), and pack_sft's prose layer is the
                # authority on that, so fall back to it. The two sources are
                # complementary: mined roles rescue opaque names, prose_name
                # rescues names that are only used in expressions.
                readable = _prose_role(name)
                if readable:
                    votes = collections.Counter({readable: 1})
            schema.variables[name] = VariableStat(
                name=name, count=len(values), always=len(values) == n,
                integral=all(float(v).is_integer() for v in values),
                lo=min(values), hi=max(values),
                median=statistics.median(values),
                role=votes.most_common(1)[0][0] if votes else "")
        out[family] = schema
    return out


# --------------------------------------------------------------------------- #
# lookup + validation
# --------------------------------------------------------------------------- #
_CACHE: Optional[dict[str, FamilySchema]] = None


def load(path: str = DEFAULT_SCHEMA) -> dict[str, FamilySchema]:
    """The mined schema, cached. Falls back to mining if the artifact is absent."""
    global _CACHE
    if _CACHE is None:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            _CACHE = {k: FamilySchema.from_dict(v)
                      for k, v in raw.get("families", {}).items()}
        else:
            _CACHE = mine()
    return _CACHE


def for_family(name: str) -> Optional[FamilySchema]:
    """Schema for a base family, or for the base of a composed part class."""
    schemas = load()
    return schemas.get(name) or schemas.get(str(name).split("_plus_")[0])


def check(part_class: str, variables: dict) -> list[str]:
    """Warnings about a planned variable set. Never raises, never blocks.

    Three things worth saying, in descending order of how badly they bite:

    * a **missing** required variable — the family's template references it, so
      the model is being asked for a part it has no dimension for;
    * an **unknown** variable — a name this family never carried, which is the
      planner inventing vocabulary the model will not recognise;
    * a value **outside the observed range** — legal, but outside the region
      where the verified rate was measured, so it deserves a deliberate choice
      rather than an accident.
    """
    schema = for_family(part_class)
    if schema is None:
        return [f"no schema for {part_class!r}: not one of the "
                f"{len(load())} families in the training set"]

    notes: list[str] = []
    supplied = {k for k in variables if not k.startswith("att")}
    required = set(schema.required())

    for missing in sorted(required - supplied):
        notes.append(f"missing {missing!r} — {schema.family} always carries it "
                     f"({schema.variables[missing].describe()})")
    for extra in sorted(supplied - set(schema.variables)):
        notes.append(f"{extra!r} is not a {schema.family} variable; known: "
                     f"{', '.join(sorted(schema.variables))}")
    for name in sorted(supplied & set(schema.variables)):
        value = variables[name]
        stat = schema.variables[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not (stat.lo <= float(value) <= stat.hi):
            notes.append(f"{name}={value:g} is outside the observed range "
                         f"{stat.lo:g}..{stat.hi:g} for {schema.family}")
    return notes


def describe(part_class: str) -> str:
    """The schema block for a family, ready to put in front of a planner."""
    schema = for_family(part_class)
    return schema.describe() if schema else f"unknown family: {part_class}"


def check_guards(part_class: str, variables: dict) -> list[dict]:
    """Evaluate the family's own preconditions against a proposed variable set.

    ``[{id, expr, value, holds}]``. This is the whole reason the guards are in
    the schema: a planner can be stopped from proposing a part the verifier
    would refuse, before a kernel is started and before the model is asked for
    anything. The arithmetic is the same ``orion.expr`` the forge uses, so a
    guard that holds here holds there.

    Guards referencing a variable that is absent are skipped rather than failed
    — ``bolted_flange``'s gland guard only applies to the variant that has a
    gland, and failing it on the plain flange would be nonsense.
    """
    schema = for_family(part_class)
    if schema is None:
        return []
    from . import expr as E

    rows: list[dict] = []
    for gid, target in sorted(schema.preconditions.items()):
        try:
            value = E.evaluate(target, variables)
        except E.ExprError:
            continue          # optional variable absent: guard does not apply
        except (TypeError, ValueError):
            continue
        rows.append({"id": gid, "expr": target, "value": value,
                     "holds": value > 0})
    return rows


# --------------------------------------------------------------------------- #
# prose -> canonical variable
# --------------------------------------------------------------------------- #
#: Words a user reaches for, and the role words they imply. Intentionally small:
#: a wrong match silently assigns a real number to the wrong dimension, which is
#: worse than no match at all — an unmatched dimension comes back as an open
#: question, and a mismatched one comes back as a confidently wrong part.
_SYNONYMS = {
    "thick": "extrude depth", "thickness": "extrude depth",
    "deep": "cut depth", "depth": "cut depth",
    "long": "length (X)", "length": "length (X)",
    "wide": "width (Y)", "width": "width (Y)",
    "tall": "extrude depth", "height": "extrude depth",
    "bore": "radius", "hole": "hole radius",
    "wall": "wall thickness",
    "pcd": "bolt-circle radius", "bolt circle": "bolt-circle radius",
    "count": "count", "number": "count", "qty": "count",
    "angle": "draft angle",
}

#: Saying "diameter" and storing it in a radius variable is a factor-of-two
#: error that builds cleanly and verifies against its own wrong prediction.
_DIAMETER_WORDS = ("diameter", "dia", "across", "ø", "φ")

#: How ``pack_sft.prose_name`` renders an attachment variable: "first feature
#: rib height" is ``att0_rh``. Those belong to composition, not to the base
#: family a planner is filling in.
_ATTACHMENT_PHRASE = re.compile(
    r"^(first|second|third|fourth|fifth|#\d+)\s+feature\b")


@dataclass
class Match:
    """One resolved dimension: which variable, and what to do with the number."""
    variable: str
    role: str
    halve: bool = False            # user stated a diameter, variable is a radius
    via: str = "role"              # role | name | synonym

    def apply(self, value: float) -> float:
        return value / 2.0 if self.halve else value


def resolve(part_class: str, phrase: str) -> Optional[Match]:
    """Map a user's words for a dimension onto a family's canonical variable.

    Returns None when nothing matches or when more than one variable matches
    equally well. Ambiguity is a question for the user, not a coin flip: an
    unresolved dimension is visible and recoverable, while a wrongly-resolved
    one produces a part that builds, verifies against its own mistaken
    prediction, and is silently not what was asked for.
    """
    schema = for_family(part_class)
    if schema is None or not phrase:
        return None

    text = str(phrase).strip().lower()

    # "first feature rib height" is pack_sft's phrasing for att0_rh — a
    # composed attachment, not a base-family variable. Matching it would write
    # an attachment's dimension into whichever base variable happens to share a
    # word ("height"), which is the confidently-wrong outcome this function
    # exists to avoid. Attachments are placed by composition, not planned here.
    if _ATTACHMENT_PHRASE.match(text):
        return None

    wants_radius_from_diameter = any(w in text for w in _DIAMETER_WORDS)

    # 1. the variable named outright ("pt", "flange_t")
    for name in schema.variables:
        if text == name.lower():
            return Match(name, schema.variables[name].role, False, "name")

    # 2. the exact inverse of pack_sft.prose_name — "barrel height" -> barrel_h.
    #    This is how the corpus itself phrases a dimension to a user, so it is
    #    the highest-value matcher: whatever the generator could say, this reads
    #    back. Checked before roles because it is exact rather than semantic.
    from .pack_sft import prose_name

    hits = [n for n in schema.variables if prose_name(n).lower() == text]
    if len(hits) == 1:
        return Match(hits[0], schema.variables[hits[0]].role, False, "prose")

    # 3. the role stated outright ("hole radius", "extrude depth")
    hits = [n for n, v in schema.variables.items()
            if v.role and v.role.lower() == text]
    if len(hits) == 1:
        return Match(hits[0], schema.variables[hits[0]].role, False, "role")

    # 4. a synonym mapped onto a role, plus the diameter rule
    target = None
    for word, role in _SYNONYMS.items():
        if word in text:
            target = role
            break
    if target is None and wants_radius_from_diameter:
        target = "radius"
    if target is None:
        return None

    hits = [n for n, v in schema.variables.items() if v.role == target]
    if not hits and target == "radius":
        hits = [n for n, v in schema.variables.items()
                if v.role and v.role.endswith("radius")]
    if len(hits) != 1:
        return None                # zero or ambiguous — ask, do not guess

    role = schema.variables[hits[0]].role
    halve = wants_radius_from_diameter and role.endswith("radius")
    return Match(hits[0], role, halve, "synonym")


#: "barrel radius 29" / "bore radius of 7" / "flange thickness = 12" / "29 mm
#: barrel radius". Units are optional and ignored — the corpus is millimetres
#: throughout and a unit word must not break the match.
_VALUE_AFTER = r"(?:\s*(?:of|is|at|=|:)?\s*)(-?\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\b"
_VALUE_BEFORE = r"(-?\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s+"


def extract_for_family(message: str, part_class: str) -> dict[str, float]:
    """Find this family's variables in a sentence, by looking for each one.

    Directed extraction, not generic parsing, and the difference is not
    cosmetic. A general dimension parser reads "barrel radius 29, bc radius 48,
    bore radius 7" as three things called *radius* and keeps one of them — the
    qualifier is what distinguishes them and it is exactly what gets stripped.
    Searching for ``barrel_r`` specifically cannot make that mistake, because
    the phrase it looks for is the whole phrase.

    Longest phrase first, so "barrel radius" is consumed before a bare "radius"
    can claim the same number.
    """
    schema = for_family(part_class)
    if schema is None or not message:
        return {}
    from .pack_sft import prose_name

    text = " ".join(str(message).lower().split())

    # Roles carry an axis annotation for the reader — "length (X)" — which no
    # user types. Search the stripped form too, but only where it stays
    # unambiguous: a phrase that could mean two of this family's variables is
    # worse than no phrase, because it silently claims one of them.
    # Phrases are tiered by how directly they name the variable, and ambiguity
    # is resolved WITHIN a tier rather than across all of them. Flattening the
    # tiers cost real matches: adding "height" as a synonym for one variable
    # collided with another variable literally called height, and the
    # uniqueness filter then discarded both — including the exact name that had
    # always worked.
    #   0: the variable itself, its prose reading, its full role
    #   1: the role with the axis annotation stripped
    #   2: the words people use instead
    tiers: list[dict[str, set]] = [{}, {}, {}]

    def offer(tier: int, phrase: str, name: str) -> None:
        if phrase and not phrase.isdigit():
            tiers[tier].setdefault(phrase, set()).add(name)

    for name, stat in schema.variables.items():
        offer(0, prose_name(name).lower(), name)
        offer(0, name.lower(), name)
        if stat.role:
            role = stat.role.lower()
            offer(0, role, name)
            bare = re.sub(r"\s*\([^)]*\)", "", role).strip()
            offer(1, bare, name)
            # Without these, "120 mm long" says nothing about a variable whose
            # role is "length (X)" — the synonym table existed in ``resolve``
            # and was missing here, so a natural sentence lost dimensions a
            # corpus-phrased one kept.
            for word, target in _SYNONYMS.items():
                if target.lower() in (role, bare):
                    offer(2, word, name)

    candidates: list[tuple[str, str]] = []
    for tier in tiers:
        rung = [(phrase, next(iter(names)))
                for phrase, names in tier.items() if len(names) == 1]
        rung.sort(key=lambda p: -len(p[0]))
        candidates.extend(rung)

    found: dict[str, float] = {}

    # Attachment clauses are consumed up front so nothing else can claim their
    # numbers. "first feature centre x 45.44" is att0_cx, but a base variable
    # whose role is also "centre x" will happily match the same text and take a
    # value belonging to a different feature — measured, that put 45.44 into a
    # seed_cx whose true value was -52.25. The same mistake ``resolve`` refuses
    # by name has to be refused here by position.
    consumed: list[tuple[int, int]] = [
        m.span() for m in re.finditer(
            r"(?:first|second|third|fourth|fifth|#\d+)\s+feature\b[^,;.]*", text)]

    def overlaps(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in consumed)

    for phrase, name in candidates:
        if name in found:
            continue
        # Word boundaries are not optional. Several families name a variable
        # with a single letter, and "6061-T6 aluminium" contains a ``t``
        # followed by a 6 — which read as "thickness = 6" and silently invented
        # a dimension from an alloy temper designation.
        quoted = r"\b" + re.escape(phrase) + r"\b"
        for pattern in (quoted + _VALUE_AFTER, _VALUE_BEFORE + quoted):
            for hit in re.finditer(pattern, text):
                if overlaps(hit.start(), hit.end()):
                    continue
                found[name] = float(hit.group(1))
                consumed.append((hit.start(), hit.end()))
                break
            if name in found:
                break
    return found


def resolve_dimensions(part_class: str, dimensions: dict[str, float]
                       ) -> tuple[dict[str, float], dict[str, float]]:
    """``(canonical, unresolved)`` for a bag of prose-keyed dimensions.

    This is the bridge from what the user said to what the model must be told:
    ``EngineeringSpec.dimensions`` in, ``EngineeringSpecification.variables``
    out. Whatever cannot be placed comes back untouched so the caller can ask
    about it rather than quietly drop it.
    """
    canonical: dict[str, float] = {}
    unresolved: dict[str, float] = {}
    for phrase, value in (dimensions or {}).items():
        match = resolve(part_class, phrase)
        if match is None:
            unresolved[phrase] = value
        else:
            canonical[match.variable] = match.apply(float(value))
    return canonical, unresolved


# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=DEFAULT_SCHEMA)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--show", help="print one family and exit")
    args = ap.parse_args(argv)

    if args.show:
        print(describe(args.show))
        return 0

    schemas = mine(args.data, args.limit)
    payload = {"source": args.data,
               "n_families": len(schemas),
               "families": {k: v.to_dict() for k, v in sorted(schemas.items())}}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    total_vars = sum(len(s.variables) for s in schemas.values())
    unstable = [s.family for s in schemas.values()
                if any(not v.always for v in s.variables.values())]
    print(f"{len(schemas)} families, {total_vars} variables -> {args.out}")
    print(f"families with an unstable variable set: {len(unstable)}"
          + (f" {unstable}" if unstable else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
