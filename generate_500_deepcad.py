import os
import random
import json

out_dir = "e:/OrionFLow_CAD/data/deepcad_raw"
os.makedirs(out_dir, exist_ok=True)

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

for i in range(500):
    seq = []
    
    # Base shape
    base_type = random.choice(["rect", "circle"])
    if base_type == "rect":
        w, h = random.uniform(0.1, 1.0), random.uniform(0.1, 1.0)
        seq.append(_make_rect_sketch(-w, -h, w, h))
    else:
        r = random.uniform(0.2, 0.8)
        seq.append(_make_circle_sketch(r))
        
    seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.5), "boolean": "new"})
    
    # Optional join
    if random.random() < 0.5:
        join_type = random.choice(["rect", "circle"])
        if join_type == "rect":
            w, h = random.uniform(0.05, 0.2), random.uniform(0.05, 0.2)
            seq.append(_make_rect_sketch(-w, -h, w, h))
        else:
            r = random.uniform(0.05, 0.2)
            seq.append(_make_circle_sketch(r))
        seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.3), "boolean": "join"})
    
    # Optional cut
    if random.random() < 0.3:
        r = random.uniform(0.01, 0.05)
        seq.append(_make_circle_sketch(r))
        seq.append({"type": "extrude", "extent_one": random.uniform(0.1, 0.5), "boolean": "cut"})
        
    obj = {"sequence": seq}
    
    with open(os.path.join(out_dir, f"sample_{i:04d}.json"), "w") as f:
        json.dump(obj, f)

print(f"Generated 500 DeepCAD samples in {out_dir}")
