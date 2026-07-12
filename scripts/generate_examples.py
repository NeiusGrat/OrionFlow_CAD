"""Generate the 20 showcase examples through the real prompt->OFL->geometry pipeline.

Each example runs the production path (Groq LLM -> OFL code -> sandbox ->
STEP/STL/GLB), is geometry-validated (watertight, sane bounds, volume), and the
artifacts land in orionflow-ui/public/examples/ with a manifest.json the UI reads.

Usage:  OFL_LLM_PROVIDER=groq python scripts/generate_examples.py [--only id1,id2]
"""

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXAMPLES = [
    {
        "id": "m8-washer",
        "title": "M8 Flat Washer",
        "category": "Fasteners",
        "prompt": "Flat washer for M8 bolts: 24mm outer diameter, 8.4mm bore, 2mm thick",
    },
    {
        "id": "pipe-flange",
        "title": "Pipe Flange DN40",
        "category": "Piping",
        "prompt": "Pipe flange, 150mm outer diameter, 12mm thick, 48mm center bore, four M16 bolt holes (17.5mm) on 110mm PCD",
    },
    {
        "id": "nema17-mount",
        "title": "NEMA 17 Motor Mount",
        "category": "Robotics",
        "prompt": "NEMA 17 stepper motor mounting plate: 60mm square, 6mm thick, 4mm corner radius, 22.5mm center bore, four M3 holes (3.4mm) on 31mm PCD at 45 degrees",
    },
    {
        "id": "nema23-mount",
        "title": "NEMA 23 Motor Mount",
        "category": "Robotics",
        "prompt": "NEMA 23 stepper motor mount: 80mm square plate, 8mm thick, 5mm corner radius, 38.5mm center bore, four M5 clearance holes (5.5mm) on 66.7mm PCD at 45 degrees",
    },
    {
        "id": "corner-plate",
        "title": "Mounting Plate 120x80",
        "category": "General",
        "prompt": "Mounting plate 120x80mm, 6mm thick, four M5 clearance holes (5.5mm) inset 10mm from each corner",
    },
    {
        "id": "rpi4-mount",
        "title": "Raspberry Pi 4 Mount",
        "category": "Electronics",
        "prompt": "Raspberry Pi 4 mounting plate: 92x62mm, 4mm thick, 3mm corner radius, four 2.7mm holes for M2.5 standoffs in a 58x49mm rectangle pattern centered on the plate",
    },
    {
        "id": "softjaw-blank",
        "title": "Soft Jaw Blank",
        "category": "Workholding",
        "prompt": "Vise soft jaw blank 100x50mm, 20mm thick, 6mm fillet on the vertical edges, two M6 clearance holes (6.6mm) spaced 60mm apart on the horizontal center line",
    },
    {
        "id": "enclosure-base",
        "title": "Electronics Enclosure",
        "category": "Electronics",
        "prompt": "Electronics enclosure base 100x64mm, 25mm tall, 4mm corner radius, hollowed out with 2.5mm walls and an open top",
    },
    {
        "id": "bearing-housing",
        "title": "6202 Bearing Housing",
        "category": "Power Transmission",
        "prompt": "Flanged bearing housing for a 6202 bearing: 55mm diameter base 6mm thick, 40mm diameter boss 12mm tall on top, 35mm bore through everything, four M4 holes (4.5mm) on 46mm PCD",
    },
    {
        "id": "counterbore-plate",
        "title": "Counterbored Plate",
        "category": "Machining",
        "prompt": "Square plate 60x60mm, 10mm thick, with a central counterbored hole for an M6 socket head cap screw: 11mm counterbore 6.5mm deep, then 6.6mm clearance hole through",
    },
    {
        "id": "orifice-plate",
        "title": "Orifice Plate",
        "category": "Process",
        "prompt": "Orifice plate 90mm outer diameter, 3mm thick, 8mm center orifice, four M8 bolt holes (8.4mm) on 70mm PCD",
    },
    {
        "id": "stepped-spacer",
        "title": "Stepped Spacer",
        "category": "Fasteners",
        "prompt": "Stepped spacer: 30mm diameter base 8mm tall, 20mm diameter upper section 12mm tall on top, 8.4mm bore through for an M8 bolt",
    },
    {
        "id": "flange-gasket",
        "title": "Flange Gasket",
        "category": "Piping",
        "prompt": "Flange gasket: 120mm outer diameter, 60mm inner bore, 1.5mm thick, eight M10 bolt holes (10.5mm) on 95mm PCD",
    },
    {
        "id": "speaker-grille",
        "title": "Speaker Grille",
        "category": "Consumer",
        "prompt": "Speaker grille disc 80mm diameter, 2mm thick, with a 6mm center hole and three rings of 5mm holes: 6 holes on 20mm PCD, 12 holes on 40mm PCD, 16 holes on 60mm PCD",
    },
    {
        "id": "shaft-collar",
        "title": "Shaft Collar Blank",
        "category": "Power Transmission",
        "prompt": "Shaft collar blank: 32mm outer diameter, 10mm wide, 12mm bore, 0.5mm chamfer on the top and bottom edges",
    },
    {
        "id": "2020-endcap",
        "title": "2020 Extrusion End Cap",
        "category": "Framing",
        "prompt": "End cap plate for 2020 aluminium extrusion: 20x20mm, 4mm thick, 2mm corner radius, single M5 clearance hole (5.5mm) in the center",
    },
    {
        "id": "drill-jig",
        "title": "Drill Jig Plate",
        "category": "Tooling",
        "prompt": "Drill jig plate 100x40mm, 8mm thick, with a row of five 6mm holes spaced 18mm apart along the horizontal center line, pattern centered on the plate",
    },
    {
        "id": "gland-plate",
        "title": "Cable Gland Plate",
        "category": "Electrical",
        "prompt": "Electrical panel gland plate 110x70mm, 3mm thick, three 20.4mm holes for M20 cable glands spaced 30mm apart along the horizontal center line, four M4 corner holes (4.5mm) inset 6mm",
    },
    {
        "id": "pulley-blank",
        "title": "Pulley Blank",
        "category": "Power Transmission",
        "prompt": "Pulley blank: 70mm diameter disc 15mm thick, 30mm diameter hub boss 8mm tall on top, 10mm center bore through, six 12mm lightening holes on 44mm PCD",
    },
    {
        "id": "lamp-base",
        "title": "Lamp Base",
        "category": "Consumer",
        "prompt": "Round lamp base 140mm diameter, 12mm thick, 2mm chamfer on the top edge, 8mm cable hole offset 50mm from center, three M4 holes (4.5mm) on 120mm PCD",
    },
]

UI_EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "orionflow-ui",
    "public",
    "examples",
)


def validate_geometry(stl_path: str) -> dict:
    """Watertightness + sanity checks. Returns stats dict or raises ValueError."""
    import trimesh

    mesh = trimesh.load(stl_path)
    if not mesh.is_watertight:
        raise ValueError("mesh is not watertight")
    if mesh.volume <= 1.0:
        raise ValueError(f"degenerate volume {mesh.volume:.2f} mm^3")
    extent = mesh.bounds[1] - mesh.bounds[0]
    if max(extent) > 500 or max(extent) < 1:
        raise ValueError(f"suspicious extent {extent.tolist()}")
    return {
        "volume_mm3": round(float(mesh.volume), 1),
        "bbox_mm": [round(float(v), 1) for v in extent],
        "triangles": int(len(mesh.faces)),
    }


def generate_one(svc, example: dict, max_attempts: int = 3) -> dict:
    """Run one example through the pipeline until it passes validation."""
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        resp = svc.generate_from_prompt(example["prompt"])
        if not resp.success:
            last_error = resp.error or "generation failed"
            if "rate" in last_error.lower() or "429" in last_error:
                print(f"    rate limited, sleeping 60s...")
                time.sleep(60)
            else:
                time.sleep(10)
            continue

        rid = resp.files.stl.split("/")[-2]
        from app.services.ofl_sandbox import OUTPUT_BASE

        out_dir = os.path.join(OUTPUT_BASE, rid)
        stl = os.path.join(out_dir, "part.stl")
        step = os.path.join(out_dir, "part.step")
        glb = os.path.join(out_dir, "part.glb")
        try:
            stats = validate_geometry(stl)
        except ValueError as e:
            last_error = f"geometry validation: {e}"
            print(f"    attempt {attempt}: {last_error}")
            time.sleep(5)
            continue

        if not (os.path.exists(step) and os.path.exists(glb)):
            last_error = "missing STEP or GLB artifact"
            continue

        for src, ext in ((glb, "glb"), (step, "step"), (stl, "stl")):
            shutil.copyfile(src, os.path.join(UI_EXAMPLES_DIR, f"{example['id']}.{ext}"))

        return {
            **example,
            "ofl_code": resp.ofl_code,
            "parameters": [
                {"name": p.name, "value": p.value} for p in resp.parameters
            ],
            "files": {
                "glb": f"/examples/{example['id']}.glb",
                "step": f"/examples/{example['id']}.step",
                "stl": f"/examples/{example['id']}.stl",
            },
            "stats": stats,
        }
    raise RuntimeError(f"{example['id']} failed after {max_attempts} attempts: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated example ids to regenerate")
    args = parser.parse_args()

    os.environ.setdefault("OFL_LLM_PROVIDER", "groq")
    from app.services.ofl_generation_service import OFLGenerationService

    svc = OFLGenerationService()
    os.makedirs(UI_EXAMPLES_DIR, exist_ok=True)

    manifest_path = os.path.join(UI_EXAMPLES_DIR, "manifest.json")
    manifest = {"examples": []}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    by_id = {e["id"]: e for e in manifest["examples"]}

    only = set(args.only.split(",")) if args.only else None
    todo = [e for e in EXAMPLES if (only is None or e["id"] in only)]
    if only is None:
        todo = [e for e in todo if e["id"] not in by_id]  # resume support

    failures = []
    for i, example in enumerate(todo):
        print(f"[{i + 1}/{len(todo)}] {example['id']}: {example['title']}")
        try:
            entry = generate_one(svc, example)
            by_id[example["id"]] = entry
            print(f"    OK  volume={entry['stats']['volume_mm3']} mm^3, "
                  f"bbox={entry['stats']['bbox_mm']}")
        except RuntimeError as e:
            failures.append(str(e))
            print(f"    FAILED: {e}")

        # keep manifest ordered like EXAMPLES and write after every part (resumable)
        manifest["examples"] = [by_id[e["id"]] for e in EXAMPLES if e["id"] in by_id]
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        if i < len(todo) - 1:
            time.sleep(15)  # stay under Groq free-tier TPM

    print(f"\nDone: {len(manifest['examples'])}/{len(EXAMPLES)} examples in manifest")
    for f_ in failures:
        print(f"  FAILED: {f_}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
