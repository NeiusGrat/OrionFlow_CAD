"""Phase 5 rejection / clarification training samples.

Produces ~200 ShareGPT JSONL samples in four categories:

    1. IMPOSSIBLE    - user asks for physically impossible geometry
                       (hole bigger than plate, wall thicker than box, etc.)
    2. AMBIGUOUS     - critical dimensions missing; model should ask
    3. OUT_OF_SCOPE  - request is not a mechanical CAD part
    4. PARTIAL       - request is under-specified but workable; model
                       generates a valid part with assumed defaults and
                       states what it assumed.

The goal is to teach the model refusal / clarification behavior so it
does not hallucinate a broken part.

Usage:
    python scripts/generate_rejections.py \
        --output data/build123d_ftc/rejection_samples.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. If the request is physically impossible, ambiguous, or "
    "out of scope, explain the problem clearly instead of producing broken "
    "code. If the request is under-specified but workable, state your "
    "assumptions and generate the part."
)


def fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# 1. IMPOSSIBLE geometry
# ---------------------------------------------------------------------------

IMPOSSIBLE_TEMPLATES = [
    {
        "prompt": "Make a {w}x{d}x{t}mm plate with a {hole}mm hole in the center.",
        "pick": lambda r: {
            "w": r.choice([20, 30, 40]),
            "d": r.choice([20, 30, 40]),
            "t": r.choice([3, 5, 8]),
            "hole": r.choice([50, 60, 80, 100]),
        },
        "check": lambda p: p["hole"] >= min(p["w"], p["d"]),
        "reason": (
            "The requested {hole}mm hole is larger than the plate "
            "(min dimension {minwd}mm). A hole cannot exceed the part it "
            "is cut from."
        ),
        "fix": (
            "Reduce the hole diameter below {minwd}mm, or increase the "
            "plate to at least {minplate}mm on its shortest side."
        ),
    },
    {
        "prompt": "Design a {w}x{d}x{h}mm hollow box with {wall}mm walls.",
        "pick": lambda r: {
            "w": r.choice([20, 30, 40]),
            "d": r.choice([20, 30, 40]),
            "h": r.choice([20, 30, 40]),
            "wall": r.choice([15, 20, 25, 30]),
        },
        "check": lambda p: p["wall"] * 2 >= min(p["w"], p["d"], p["h"]),
        "reason": (
            "A {wall}mm wall on both sides consumes {doublewall}mm, which "
            "exceeds the smallest dimension of the box ({mindim}mm). There "
            "is no room for a cavity."
        ),
        "fix": (
            "Use walls thinner than {maxwall}mm, or grow the box so its "
            "smallest dimension is at least {minbox}mm."
        ),
    },
    {
        "prompt": "Make a {od}mm OD flange with a {bore}mm bore and 4 bolt holes on a {pcd}mm PCD.",
        "pick": lambda r: {
            "od": r.choice([40, 50, 60]),
            "bore": r.choice([50, 60, 70]),
            "pcd": r.choice([80, 100]),
        },
        "check": lambda p: p["bore"] >= p["od"] or p["pcd"] >= p["od"],
        "reason": (
            "You asked for a {od}mm outer diameter but specified a "
            "{bore}mm bore and/or a {pcd}mm bolt circle. Both the bore "
            "and the PCD must be strictly smaller than the OD."
        ),
        "fix": (
            "Either increase the OD above {pcd}mm (and the bore above "
            "{bore}mm), or shrink the bore/PCD to fit inside a {od}mm flange."
        ),
    },
    {
        "prompt": "Cut a {slot}mm slot across a {w}mm wide bracket.",
        "pick": lambda r: {
            "slot": r.choice([30, 40, 50]),
            "w": r.choice([15, 20, 25]),
        },
        "check": lambda p: p["slot"] >= p["w"],
        "reason": (
            "A {slot}mm slot does not fit inside a {w}mm bracket. The "
            "slot would split the bracket into two pieces."
        ),
        "fix": (
            "Use a slot shorter than {w}mm, or widen the bracket to at "
            "least {minw}mm so the slot clears its edges."
        ),
    },
    {
        "prompt": "Make a tube with {od}mm outer diameter and {id}mm inner diameter.",
        "pick": lambda r: {
            "od": r.choice([10, 15, 20, 25]),
            "id": r.choice([20, 25, 30, 35]),
        },
        "check": lambda p: p["id"] >= p["od"],
        "reason": (
            "The inner diameter ({id}mm) is not smaller than the outer "
            "diameter ({od}mm), so there is no wall material left."
        ),
        "fix": (
            "Set the inner diameter below {od}mm (e.g. {suggested_id}mm "
            "for a 2mm wall)."
        ),
    },
]


def _impossible_sample(rng: random.Random) -> dict:
    # keep picking until check is satisfied
    for _ in range(25):
        tpl = rng.choice(IMPOSSIBLE_TEMPLATES)
        p = tpl["pick"](rng)
        if tpl["check"](p):
            break
    else:
        return None  # pragma: no cover
    prompt = tpl["prompt"].format(**p)

    ctx = dict(p)
    if "w" in p and "d" in p:
        ctx["minwd"] = min(p["w"], p["d"])
        if "hole" in p:
            ctx["minplate"] = p["hole"] + 4
    if "wall" in p:
        mindim = min(p["w"], p["d"], p["h"])
        ctx["doublewall"] = p["wall"] * 2
        ctx["mindim"] = mindim
        ctx["maxwall"] = (mindim // 2) - 1
        ctx["minbox"] = p["wall"] * 2 + 5
    if "slot" in p and "w" in p:
        ctx["minw"] = p["slot"] + 4
    if "od" in p and "id" in p:
        ctx["suggested_id"] = max(1, p["od"] - 4)

    reason = tpl["reason"].format(**ctx)
    fix = tpl["fix"].format(**ctx)

    assistant = (
        "I can't build that part as specified.\n\n"
        f"Problem: {reason}\n\n"
        f"Suggestion: {fix}\n\n"
        "If you confirm the corrected dimensions I'll generate the code."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ],
        "source": "phase5_impossible",
        "category": "impossible",
    }


# ---------------------------------------------------------------------------
# 2. AMBIGUOUS — missing dimensions
# ---------------------------------------------------------------------------

AMBIGUOUS_PROMPTS = [
    (
        "Make a mounting plate with holes.",
        [
            "plate length and width",
            "plate thickness",
            "hole diameter",
            "number of holes and their spacing",
        ],
    ),
    (
        "I need a bracket.",
        [
            "bracket type (L, Z, U, gusset)",
            "leg lengths",
            "material thickness",
            "hole pattern (if any)",
        ],
    ),
    (
        "Design a motor mount.",
        [
            "motor frame size (NEMA 14/17/23/34?)",
            "plate outer dimensions",
            "mounting hole pattern for the base",
            "cable clearance slot?",
        ],
    ),
    (
        "Give me a shaft.",
        [
            "shaft length",
            "shaft diameter (or multiple steps?)",
            "key/flats/threads?",
            "end features (chamfers, fillets)",
        ],
    ),
    (
        "Build a box.",
        [
            "external dimensions (LxWxH)",
            "open or closed (lid?)",
            "wall thickness",
            "mounting features",
        ],
    ),
    (
        "Make a flange.",
        [
            "outer diameter",
            "bore diameter",
            "bolt circle diameter and bolt count",
            "flange thickness and bolt hole size",
        ],
    ),
    (
        "I want a pulley.",
        [
            "pulley outer diameter",
            "belt type (V-belt, timing belt, flat)",
            "bore diameter and keyway?",
            "overall width / hub length",
        ],
    ),
    (
        "Make a gear.",
        [
            "module (or diametral pitch)",
            "tooth count",
            "face width",
            "bore diameter",
        ],
    ),
    (
        "Make a handle.",
        [
            "handle type (bar, lever, knob)",
            "overall length",
            "grip diameter",
            "mounting method (threaded? bolted?)",
        ],
    ),
    (
        "Design an enclosure.",
        [
            "external dimensions",
            "wall thickness",
            "lid style (snap, screws?)",
            "cable/connector openings",
        ],
    ),
    (
        "Build a cam.",
        [
            "base circle radius",
            "lift profile or max lift",
            "follower type (flat, roller)",
            "shaft bore and keyway",
        ],
    ),
    (
        "Make a spacer.",
        [
            "outer diameter",
            "inner diameter / bore",
            "length (height)",
            "material?",
        ],
    ),
    (
        "I need a clamp.",
        [
            "clamped diameter or width",
            "clamp style (split, worm, toggle)",
            "mounting hole pattern",
            "overall thickness",
        ],
    ),
    (
        "Make a coupling.",
        [
            "both shaft diameters",
            "coupling type (rigid, jaw, Oldham)",
            "overall length",
            "set screw / keyway details",
        ],
    ),
    (
        "Give me a baseplate with standoffs.",
        [
            "plate LxW",
            "plate thickness",
            "standoff height and diameter",
            "number and position of standoffs",
        ],
    ),
]


def _ambiguous_sample(rng: random.Random) -> dict:
    prompt, needs = rng.choice(AMBIGUOUS_PROMPTS)
    # pick 3 to 4 questions
    k = min(len(needs), rng.choice([3, 4]))
    picks = rng.sample(needs, k)
    lines = [
        "Before I can generate the part I need a few dimensions:",
        "",
    ]
    for i, q in enumerate(picks, 1):
        lines.append(f"{i}. {q}")
    lines.append("")
    lines.append(
        "Share those numbers (or say 'use defaults') and I'll produce the "
        "Build123d code."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "\n".join(lines)},
        ],
        "source": "phase5_ambiguous",
        "category": "ambiguous",
    }


# ---------------------------------------------------------------------------
# 3. OUT OF SCOPE
# ---------------------------------------------------------------------------

OUT_OF_SCOPE = [
    ("Write me a poem about a lathe.", "creative writing"),
    ("What's the weather in Mumbai today?", "weather forecast"),
    ("Translate 'hello world' to French.", "language translation"),
    ("Tell me a joke about engineers.", "jokes"),
    ("Explain the Krebs cycle.", "biology explanation"),
    ("Write SQL to count users per day.", "database query"),
    ("Generate a React component for a login form.", "web UI code"),
    ("How do I cook pasta?", "cooking advice"),
    ("Summarize the plot of Hamlet.", "literary summary"),
    ("Debug my JavaScript fetch call.", "general-purpose JS debugging"),
    ("Recommend a laptop for under $1000.", "product recommendations"),
    ("Plan a 3-day trip to Goa.", "travel planning"),
    ("Write a Dockerfile for a Node.js app.", "devops/containerization"),
    ("Draft an email to my landlord.", "email drafting"),
    ("Explain quantum entanglement.", "physics lecture"),
    ("What's 47 times 83?", "arithmetic helper"),
    ("Teach me Mandarin numbers 1-10.", "language tutoring"),
    ("Predict tomorrow's stock price for NVDA.", "financial prediction"),
    ("Write a SQL schema for an e-commerce site.", "database design"),
    ("Convert this Python script to Go.", "general language translation"),
    ("Generate a CSS gradient background.", "web styling"),
    ("Tell me about the French Revolution.", "history tutoring"),
    ("Write a unit test for my React hook.", "frontend testing"),
    ("How do I set up a Kubernetes cluster?", "infrastructure setup"),
    ("Give me a recipe for tiramisu.", "cooking recipe"),
]


def _scope_sample(rng: random.Random) -> dict:
    prompt, topic = rng.choice(OUT_OF_SCOPE)
    assistant = (
        f"I'm OrionFlow, a CAD copilot focused on generating Build123d code "
        f"for mechanical parts. {topic.capitalize()} is outside what I can "
        "help with.\n\n"
        "If you describe a part you'd like to design (plate, bracket, motor "
        "mount, flange, shaft, enclosure, etc.) with its key dimensions, "
        "I'll generate the Build123d code for it."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ],
        "source": "phase5_out_of_scope",
        "category": "out_of_scope",
    }


# ---------------------------------------------------------------------------
# 4. PARTIAL — under-specified but workable (defaults + note)
# ---------------------------------------------------------------------------

PARTIAL_CASES = [
    {
        "prompt": "Make me a small mounting plate with 4 corner holes.",
        "assumptions": [
            "60x40mm plate, 5mm thick",
            "M4 clearance holes (4.5mm) at 6mm inset from each corner",
        ],
        "params": [
            ("L", 60.0, "plate length"),
            ("W", 40.0, "plate width"),
            ("t", 5.0, "thickness"),
            ("hole_d", 4.5, "M4 clearance"),
            ("inset", 6.0, "corner inset"),
        ],
        "body": [
            "# Feature 1: Base plate",
            "with BuildSketch() as s:",
            "    Rectangle(L, W)",
            "extrude(amount=t)",
            "# Feature 2: Four M4 corner holes",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations(",
            "        (-(L/2 - inset), -(W/2 - inset)),",
            "        ( (L/2 - inset), -(W/2 - inset)),",
            "        (-(L/2 - inset),  (W/2 - inset)),",
            "        ( (L/2 - inset),  (W/2 - inset)),",
            "    ):",
            "        Circle(hole_d / 2)",
            "extrude(amount=-t, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "I need a simple L bracket for a shelf.",
        "assumptions": [
            "40x40mm legs with 30mm width, 3mm stock",
            "Two M5 clearance holes (5.5mm) per leg",
        ],
        "params": [
            ("leg", 40.0, "leg length"),
            ("W", 30.0, "width"),
            ("t", 3.0, "stock thickness"),
            ("hole_d", 5.5, "M5 clearance"),
        ],
        "body": [
            "# Feature 1: Vertical leg",
            "with BuildSketch(Plane.XZ) as s:",
            "    with Locations((0, leg/2)):",
            "        Rectangle(W, leg)",
            "extrude(amount=t)",
            "# Feature 2: Horizontal leg",
            "with BuildSketch() as s:",
            "    with Locations((0, leg/2 + t/2)):",
            "        Rectangle(W, leg)",
            "extrude(amount=t)",
        ],
    },
    {
        "prompt": "Give me a spacer for a 6mm bolt.",
        "assumptions": [
            "12mm outer diameter, 6.5mm bore, 10mm long",
        ],
        "params": [
            ("od", 12.0, "outer diameter"),
            ("bore", 6.5, "bolt clearance"),
            ("L", 10.0, "length"),
        ],
        "body": [
            "# Feature 1: Cylindrical body",
            "with BuildSketch() as s:",
            "    Circle(od / 2)",
            "extrude(amount=L)",
            "# Feature 2: Through bore",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    Circle(bore / 2)",
            "extrude(amount=-L, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Make a cover plate for an electronics enclosure.",
        "assumptions": [
            "100x60mm plate, 2mm thick",
            "Four M3 clearance holes (3.4mm) inset 5mm from corners",
        ],
        "params": [
            ("L", 100.0, "plate length"),
            ("W", 60.0, "plate width"),
            ("t", 2.0, "thickness"),
            ("hole_d", 3.4, "M3 clearance"),
            ("inset", 5.0, "corner inset"),
        ],
        "body": [
            "# Feature 1: Base plate",
            "with BuildSketch() as s:",
            "    Rectangle(L, W)",
            "extrude(amount=t)",
            "# Feature 2: Four M3 corner holes",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations(",
            "        (-(L/2 - inset), -(W/2 - inset)),",
            "        ( (L/2 - inset), -(W/2 - inset)),",
            "        (-(L/2 - inset),  (W/2 - inset)),",
            "        ( (L/2 - inset),  (W/2 - inset)),",
            "    ):",
            "        Circle(hole_d / 2)",
            "extrude(amount=-t, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Design a standoff for a PCB.",
        "assumptions": [
            "8mm hex outer, 3.2mm M3 clearance bore, 15mm tall",
        ],
        "params": [
            ("af", 8.0, "hex flat-to-flat"),
            ("bore", 3.2, "M3 clearance"),
            ("H", 15.0, "height"),
        ],
        "body": [
            "# Feature 1: Hex body",
            "with BuildSketch() as s:",
            "    RegularPolygon(radius=af/2, side_count=6, major_radius=False)",
            "extrude(amount=H)",
            "# Feature 2: Through bore",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    Circle(bore / 2)",
            "extrude(amount=-H, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Make a small flanged bushing.",
        "assumptions": [
            "Body 10mm OD x 15mm long, flange 16mm OD x 2mm thick, 6mm bore",
        ],
        "params": [
            ("body_od", 10.0, "body OD"),
            ("body_L", 15.0, "body length"),
            ("flange_od", 16.0, "flange OD"),
            ("flange_t", 2.0, "flange thickness"),
            ("bore", 6.0, "bore"),
        ],
        "body": [
            "# Feature 1: Flange",
            "with BuildSketch() as s:",
            "    Circle(flange_od / 2)",
            "extrude(amount=flange_t)",
            "# Feature 2: Body",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    Circle(body_od / 2)",
            "extrude(amount=body_L)",
            "# Feature 3: Through bore",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    Circle(bore / 2)",
            "extrude(amount=-(flange_t + body_L), mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Make a washer.",
        "assumptions": [
            "M6 washer: 12mm OD, 6.5mm ID, 1.5mm thick",
        ],
        "params": [
            ("od", 12.0, "outer diameter"),
            ("id", 6.5, "inner diameter"),
            ("t", 1.5, "thickness"),
        ],
        "body": [
            "# Feature 1: Washer body",
            "with BuildSketch() as s:",
            "    Circle(od / 2)",
            "    Circle(id / 2, mode=Mode.SUBTRACT)",
            "extrude(amount=t)",
        ],
    },
    {
        "prompt": "I want a dowel pin block.",
        "assumptions": [
            "30x20x10mm block with two 6mm press-fit holes 20mm apart",
        ],
        "params": [
            ("L", 30.0, "block length"),
            ("W", 20.0, "block width"),
            ("H", 10.0, "block height"),
            ("pin_d", 6.0, "dowel diameter"),
            ("pitch", 20.0, "pin spacing"),
        ],
        "body": [
            "# Feature 1: Block",
            "with BuildSketch() as s:",
            "    Rectangle(L, W)",
            "extrude(amount=H)",
            "# Feature 2: Two dowel holes",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations((-pitch/2, 0), (pitch/2, 0)):",
            "        Circle(pin_d / 2)",
            "extrude(amount=-H, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Make a light duty cable clamp.",
        "assumptions": [
            "For 8mm cable: 20mm long, 14mm wide body, 3mm stock, M3 screw hole",
        ],
        "params": [
            ("cable_d", 8.0, "cable diameter"),
            ("L", 20.0, "clamp length"),
            ("W", 14.0, "clamp width"),
            ("t", 3.0, "stock thickness"),
            ("screw_d", 3.4, "M3 clearance"),
        ],
        "body": [
            "# Feature 1: Base strap",
            "with BuildSketch() as s:",
            "    SlotOverall(L, W)",
            "extrude(amount=t)",
            "# Feature 2: Cable pocket",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    Circle(cable_d / 2)",
            "extrude(amount=-t/2, mode=Mode.SUBTRACT)",
            "# Feature 3: Screw hole",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations((L/2 - W/2, 0)):",
            "        Circle(screw_d / 2)",
            "extrude(amount=-t, mode=Mode.SUBTRACT)",
        ],
    },
    {
        "prompt": "Give me a lever arm.",
        "assumptions": [
            "60mm long, 12mm wide, 4mm thick, 6mm pivot hole at one end",
            "4mm control hole at the other end",
        ],
        "params": [
            ("L", 60.0, "arm length"),
            ("W", 12.0, "arm width"),
            ("t", 4.0, "thickness"),
            ("pivot_d", 6.0, "pivot hole"),
            ("ctrl_d", 4.0, "control hole"),
            ("end_inset", 8.0, "end inset"),
        ],
        "body": [
            "# Feature 1: Arm body",
            "with BuildSketch() as s:",
            "    SlotOverall(L, W)",
            "extrude(amount=t)",
            "# Feature 2: Pivot hole",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations((-(L/2 - end_inset), 0)):",
            "        Circle(pivot_d / 2)",
            "extrude(amount=-t, mode=Mode.SUBTRACT)",
            "# Feature 3: Control hole",
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]) as s:",
            "    with Locations(((L/2 - end_inset), 0)):",
            "        Circle(ctrl_d / 2)",
            "extrude(amount=-t, mode=Mode.SUBTRACT)",
        ],
    },
]


def _build_partial_code(params: list[tuple[str, float, str]], body: list[str]) -> str:
    lines = ["from build123d import *", "", "# --- Parameters ---"]
    for name, val, cmt in params:
        lines.append(f"{name} = {fmt(val)}  # {cmt}")
    lines.append("")
    lines.append("# --- Feature Tree ---")
    lines.append("with BuildPart() as part:")
    for b in body:
        lines.append("    " + b if b else "")
    lines.append("")
    lines.append("# --- Export ---")
    lines.append("result = part.part")
    lines.append('export_step(result, "output.step")')
    return "\n".join(lines)


def _partial_sample(rng: random.Random) -> dict:
    case = rng.choice(PARTIAL_CASES)
    code = _build_partial_code(case["params"], case["body"])
    assumption_bullets = "\n".join(f"- {a}" for a in case["assumptions"])
    assistant = (
        "Your request doesn't pin down every dimension, so I'll generate "
        "the part with sensible defaults and flag them.\n\n"
        "Assumptions:\n"
        f"{assumption_bullets}\n\n"
        "If any of these don't match what you need, share the correct "
        "numbers and I'll regenerate.\n\n"
        f"```python\n{code}\n```"
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": case["prompt"]},
            {"role": "assistant", "content": assistant},
        ],
        "source": "phase5_partial",
        "category": "partial",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--impossible", type=int, default=60)
    ap.add_argument("--ambiguous", type=int, default=60)
    ap.add_argument("--out-of-scope", dest="oos", type=int, default=40)
    ap.add_argument("--partial", type=int, default=40)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    stats = {"impossible": 0, "ambiguous": 0, "out_of_scope": 0, "partial": 0}

    with args.output.open("w", encoding="utf-8") as fout:
        seen: set[str] = set()

        def _write(rec: dict, key: str) -> None:
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats[key] += 1

        # IMPOSSIBLE: prompt-level dedupe, capped attempts
        attempts = 0
        while stats["impossible"] < args.impossible and attempts < args.impossible * 20:
            attempts += 1
            rec = _impossible_sample(rng)
            if rec is None:
                continue
            prompt = rec["messages"][1]["content"]
            tag = f"imp::{prompt}"
            if tag in seen:
                continue
            seen.add(tag)
            _write(rec, "impossible")

        # AMBIGUOUS: dedupe on (prompt, assistant) — same prompt with
        # different question subset counts as a different sample
        attempts = 0
        while stats["ambiguous"] < args.ambiguous and attempts < args.ambiguous * 20:
            attempts += 1
            rec = _ambiguous_sample(rng)
            prompt = rec["messages"][1]["content"]
            asst = rec["messages"][2]["content"]
            tag = f"amb::{prompt}::{asst}"
            if tag in seen:
                continue
            seen.add(tag)
            _write(rec, "ambiguous")

        # OUT OF SCOPE: fixed pool — emit each unique prompt once, cap at pool size
        target_oos = min(args.oos, len(OUT_OF_SCOPE))
        attempts = 0
        while stats["out_of_scope"] < target_oos and attempts < target_oos * 20:
            attempts += 1
            rec = _scope_sample(rng)
            prompt = rec["messages"][1]["content"]
            tag = f"oos::{prompt}"
            if tag in seen:
                continue
            seen.add(tag)
            _write(rec, "out_of_scope")

        # PARTIAL: fixed pool — emit each unique case once, cap at pool size
        target_partial = min(args.partial, len(PARTIAL_CASES))
        attempts = 0
        while stats["partial"] < target_partial and attempts < target_partial * 20:
            attempts += 1
            rec = _partial_sample(rng)
            prompt = rec["messages"][1]["content"]
            tag = f"par::{prompt}"
            if tag in seen:
                continue
            seen.add(tag)
            _write(rec, "partial")

    print("=== Phase 5 rejection/clarification stats ===")
    total = 0
    for k, v in stats.items():
        print(f"  {k:15s} {v}")
        total += v
    print(f"  total           {total}")
    print(f"  wrote -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
