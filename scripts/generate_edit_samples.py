"""Generate editing/modification training samples from validated build123d-FTC
base samples.

For each base sample, this produces:
    1. A PARAMETER_CHANGE edit (rewrite one parameter value)
    2. An ADD_FEATURE edit (append a center hole / fillet / chamfer / grid holes)

Output is a ShareGPT JSONL with the EDITING system prompt.

Usage:
    python scripts/generate_edit_samples.py \
        --input data/build123d_ftc/templates_valid.jsonl \
        --output data/build123d_ftc/editing_templates.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

EDIT_SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. The user will show "
    "you existing Build123d code and request a modification. Generate the "
    "complete modified code preserving the Feature Tree Convention structure. "
    "Only change what the user requested."
)

PARAM_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?)(?:\b|$)", re.MULTILINE)

# parameters we refuse to touch because they break the topology
PROTECTED_NAMES = {"nx", "ny", "n_slots", "n_bolts"}


def extract_params(code: str) -> list[tuple[str, float, str]]:
    """Return (name, value, full_line) for each numeric assignment in the
    Parameters section."""
    # find the parameters block (between '# --- Parameters ---' and next '---')
    start = code.find("# --- Parameters ---")
    end = code.find("# --- Feature Tree ---")
    if start < 0 or end < 0:
        return []
    section = code[start:end]
    out: list[tuple[str, float, str]] = []
    for line in section.splitlines():
        m = PARAM_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        val = float(m.group(2))
        if name in PROTECTED_NAMES:
            continue
        out.append((name, val, line))
    return out


def snap_value(new_val: float, old_val: float) -> float:
    """Snap the new value to a sensible precision based on the original."""
    if abs(old_val - round(old_val)) < 1e-6:
        return float(round(new_val))
    return round(new_val, 1)


def param_change_edit(
    code: str, rng: random.Random
) -> tuple[str, str, str, str] | None:
    """Return (new_code, var_name, old_val, new_val) or None if unable."""
    params = extract_params(code)
    if not params:
        return None
    name, old_val, _old_line = rng.choice(params)

    # choose a new value in ±30..80% of the old one, snapped
    sign = rng.choice([-1, 1])
    factor = 1 + sign * rng.uniform(0.3, 0.8)
    new_val = snap_value(max(0.5, old_val * factor), old_val)
    if abs(new_val - old_val) < 1e-6:
        new_val = old_val + (1.0 if sign > 0 else -1.0)
    if new_val <= 0.5:
        new_val = old_val + 2.0

    # replace ONLY the first declaration line
    pattern = re.compile(
        rf"^(\s*){re.escape(name)}\s*=\s*-?\d+(?:\.\d+)?(\s*(#.*)?)$", re.MULTILINE
    )
    replaced = [False]

    def _sub(m):
        if replaced[0]:
            return m.group(0)
        replaced[0] = True
        return f"{m.group(1)}{name} = {_fmt(new_val)}{m.group(2)}"

    new_code = pattern.sub(_sub, code, count=1)
    if not replaced[0] or new_code == code:
        return None
    return new_code, name, _fmt(old_val), _fmt(new_val)


def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Add-feature edits
# ---------------------------------------------------------------------------

ADD_CENTER_HOLE_TEMPLATE = """\

    # Feature N: Central through-hole ({dia_val}mm)
    with BuildSketch(part.faces().filter_by(Plane.XY).sort_by(Axis.Z)[-1]):
        Circle({rad_val})
    extrude(amount=-{depth_val}, mode=Mode.SUBTRACT)
"""

ADD_FILLET_TEMPLATE = """\

    # Feature N: Fillet top-face edges ({r_val}mm)
    fillet(part.faces().sort_by(Axis.Z)[-1].edges(), radius={r_val})
"""

ADD_CHAMFER_TEMPLATE = """\

    # Feature N: Chamfer top-face edges ({d_val}mm)
    chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length={d_val})
"""

ADD_GRID_HOLES_TEMPLATE = """\

    # Feature N: Four corner mounting holes (M{m_size})
    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):
        with GridLocations(30.0, 30.0, 2, 2):
            Circle({rad_val})
    extrude(amount=-{depth_val}, mode=Mode.SUBTRACT)
"""


def insert_before_export(code: str, block: str) -> str:
    """Insert `block` into the BuildPart body right before the '# --- Export ---' line."""
    marker = "# --- Export ---"
    idx = code.find(marker)
    if idx < 0:
        return code
    # find the closing of the with BuildPart() block — we need to insert INSIDE it,
    # which means the last non-empty line before `result = part.part` that is still
    # indented 4 spaces.
    # Simplest: walk backwards from the marker to the last indented (4 spaces) line.
    head = code[:idx].rstrip() + "\n"
    tail = code[idx:]
    return head + block + "\n" + tail


def add_feature_edit(
    code: str, rng: random.Random
) -> tuple[str, str] | None:
    """Return (new_code, description) or None."""
    choice = rng.choice(["center_hole", "fillet", "chamfer", "grid_holes"])
    if choice == "center_hole":
        dia = rng.choice([4.0, 5.0, 6.0, 8.0, 10.0])
        rad = dia / 2
        block = ADD_CENTER_HOLE_TEMPLATE.format(
            dia_val=_fmt(dia), rad_val=_fmt(rad), depth_val="20.0"
        )
        desc = f"Add a {_fmt(dia)}mm through-hole at the center of the top face"
    elif choice == "fillet":
        r = rng.choice([0.5, 1.0, 1.5])
        block = ADD_FILLET_TEMPLATE.format(r_val=_fmt(r))
        desc = f"Add {_fmt(r)}mm fillets to the top-face edges"
    elif choice == "chamfer":
        d = rng.choice([0.3, 0.5, 0.8])
        block = ADD_CHAMFER_TEMPLATE.format(d_val=_fmt(d))
        desc = f"Add a {_fmt(d)}mm chamfer to the top edges"
    else:  # grid_holes
        m = rng.choice([3, 4, 5, 6])
        dia = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6}[m]
        rad = dia / 2
        block = ADD_GRID_HOLES_TEMPLATE.format(
            m_size=m, rad_val=_fmt(rad), depth_val="20.0"
        )
        desc = f"Add four M{m} mounting holes in a 2x2 grid on the top face"

    new_code = insert_before_export(code, block)
    if new_code == code:
        return None
    return new_code, desc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_user_code(sample: dict) -> str:
    for m in sample.get("messages", []):
        if m.get("role") == "assistant":
            return m.get("content", "")
    return ""


def build_sharegpt(
    original_code: str,
    modified_code: str,
    modification_text: str,
    source: str,
    base_meta: dict,
) -> dict:
    user_msg = (
        f"Here is my current part:\n\n"
        f"```python\n{original_code}\n```\n\n"
        f"Modification: {modification_text}"
    )
    return {
        "messages": [
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": modified_code},
        ],
        "source": source,
        "edit_type": base_meta.get("edit_type"),
        "base_template": base_meta.get("base_template"),
        "complexity": base_meta.get("complexity", 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=31337)
    ap.add_argument(
        "--max",
        type=int,
        default=0,
        help="max output samples (0 = 2 per base)",
    )
    args = ap.parse_args()

    rng = random.Random(args.seed)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "total_base": 0,
        "param_change": 0,
        "add_feature": 0,
        "failed_param": 0,
        "failed_add": 0,
    }

    with args.input.open("r", encoding="utf-8") as fin, args.output.open(
        "w", encoding="utf-8"
    ) as fout:
        out_count = 0
        for line in fin:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            stats["total_base"] += 1
            original = extract_user_code(sample)
            if not original:
                continue
            base_meta = {
                "base_template": sample.get("template") or sample.get("origin_file"),
                "complexity": sample.get("complexity", 3),
            }

            # Edit 1: parameter change
            res = param_change_edit(original, rng)
            if res is not None:
                new_code, name, old_val, new_val = res
                mod_text = (
                    f"Change the {name} from {old_val} to {new_val}mm"
                )
                edit_source = (sample.get("source") or "base") + "_edit_param"
                rec = build_sharegpt(
                    original,
                    new_code,
                    mod_text,
                    edit_source,
                    {**base_meta, "edit_type": "param_change"},
                )
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["param_change"] += 1
                out_count += 1
            else:
                stats["failed_param"] += 1

            # Edit 2: add feature
            res = add_feature_edit(original, rng)
            if res is not None:
                new_code, desc = res
                edit_source = (sample.get("source") or "base") + "_edit_add"
                rec = build_sharegpt(
                    original,
                    new_code,
                    desc,
                    edit_source,
                    {**base_meta, "edit_type": "add_feature"},
                )
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["add_feature"] += 1
                out_count += 1
            else:
                stats["failed_add"] += 1

            if args.max and out_count >= args.max:
                break

    print("=== Edit sample stats ===")
    for k, v in stats.items():
        print(f"  {k:15s} {v}")
    print(f"  wrote {out_count} samples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
