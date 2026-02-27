"""Generate synthetic DeepCAD-like JSON samples for pipeline smoke tests."""

from __future__ import annotations

import argparse
import json
import os
import random


def _make_rect_sketch(x1, y1, x2, y2, plane_nz=1):
    return {
        "type": "sketch",
        "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": plane_nz},
        "loops": [{
            "curves": [
                {"type": "line", "start": [x1, y1], "end": [x2, y1]},
                {"type": "line", "start": [x2, y1], "end": [x2, y2]},
                {"type": "line", "start": [x2, y2], "end": [x1, y2]},
                {"type": "line", "start": [x1, y2], "end": [x1, y1]},
            ]
        }],
    }


def _make_circle_sketch(radius, center=(0, 0), plane_nz=1):
    return {
        "type": "sketch",
        "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": plane_nz},
        "loops": [{
            "curves": [
                {"type": "circle", "center": list(center), "radius": radius}
            ]
        }],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DeepCAD-like JSON test samples")
    parser.add_argument("--count", type=int, default=5, help="Number of samples to generate")
    parser.add_argument("--output-dir", default="data/deepcad_raw", help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    if args.count <= 0:
        raise ValueError("--count must be > 0")

    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    for i in range(args.count):
        seq = []

        base_type = random.choice(["rect", "circle"])
        if base_type == "rect":
            w, h = random.uniform(0.1, 1.0), random.uniform(0.1, 1.0)
            seq.append(_make_rect_sketch(-w, -h, w, h))
        else:
            r = random.uniform(0.2, 0.8)
            seq.append(_make_circle_sketch(r))

        seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.5), "boolean": "new"})

        if random.random() < 0.5:
            join_type = random.choice(["rect", "circle"])
            if join_type == "rect":
                w, h = random.uniform(0.05, 0.2), random.uniform(0.05, 0.2)
                seq.append(_make_rect_sketch(-w, -h, w, h))
            else:
                r = random.uniform(0.05, 0.2)
                seq.append(_make_circle_sketch(r))
            seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.3), "boolean": "join"})

        if random.random() < 0.3:
            r = random.uniform(0.01, 0.05)
            seq.append(_make_circle_sketch(r))
            seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.5), "boolean": "cut"})

        obj = {"sequence": seq}
        out_path = os.path.join(args.output_dir, f"sample_{i:04d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    print(f"Generated {args.count} DeepCAD samples in {args.output_dir}")


if __name__ == "__main__":
    main()
