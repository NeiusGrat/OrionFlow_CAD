"""One-process build + place + measure for an assembly.

The assembly counterpart to ``build_measure_fc.py``, and written the same way:
load the production compiler (``freecad/reconstruct.py``) and the production
measurer (``orion/measure_fc.py``) by absolute path, then drive them in *this*
interpreter. Nothing about how a component is compiled or measured is restated
here — a second implementation of either is how an assembly would start
disagreeing with the single parts it is made of.

**Why one process.** The previous arrangement spawned FreeCAD once per
component and once more to place and fuse them: N+1 interpreter startups, five
of them for a three-planet stage, which was the greater part of its ~90 s build.
Interpreter startup dominates the cycle exactly as it did for the forge loop,
and the fix is the same one ``build_measure_fc.py`` already took.

Usage (FreeCAD's Python):
    python build_assembly_fc.py --spec spec.json --out measured.json \\
        --workdir DIR --step a.step --stl a.stl

``spec.json`` is::

    {"components": [{"id": "sun", "graph": {...}, "pos": [x, y, z],
                     "rot_z": 12.5}, ...]}

``pos`` and ``rot_z`` are already numbers: every expression in the spec is
evaluated against the assembly's variables before it reaches the kernel, so
this file never sees an expression and never needs the evaluator.

The output JSON carries both levels of evidence — each component's own
measurement, and the assembly's — because both are checked, against different
assertions, by the caller.
"""

import argparse
import importlib.util
import json
import os
import sys


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _place(shape, pos, rot_z):
    """Rotate about Z then translate — the order the spec's positions assume.

    Rotation first, because a component's ``pos`` is where its origin lands and
    ``rot_z`` is its orientation about its own axis. Translating first would
    swing the part around the assembly origin instead of spinning it in place,
    which for a planet gear is the difference between meshing and orbiting.
    """
    import FreeCAD as App  # noqa: PLC0415

    out = shape.copy()
    out.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), float(rot_z or 0.0))
    out.translate(App.Vector(*[float(c) for c in pos]))
    return out


def _body_shape(doc, where):
    """The PartDesign Body tip, not the largest solid.

    A PartDesign document exposes every feature as its own object with a Shape
    — the Pad before the Pocket as well as the Pocket result — so max-by-volume
    always picks the pre-pocket blank. Any component whose last operation
    removes material would be placed, and measured, without it.
    """
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"
              and getattr(o, "Shape", None) is not None
              and not o.Shape.isNull()]
    if bodies:
        return bodies[0].Shape
    solids = [o for o in doc.Objects if getattr(o, "Shape", None) is not None
              and not o.Shape.isNull() and o.Shape.Volume > 1e-9]
    if not solids:
        raise RuntimeError(f"component {where!r} compiled to no solid")
    return max(solids, key=lambda o: o.Shape.Volume).Shape


#: Failure reasons this runner can report, as the caller's taxonomy names them.
COMPONENT_FAILED = "component_failed"
PLACEMENT_FAILED = "placement_failed"


class _Failed(Exception):
    """A classified failure. Written to --out so the caller need not read stderr.

    Scraping a kernel's stderr to decide *why* a build failed is how a message
    meant for a developer ends up in front of a user. The runner knows which
    stage it was in, so it says so.
    """

    def __init__(self, reason, detail):
        self.reason, self.detail = reason, detail
        super().__init__(detail)


def _run(args):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--step")
    ap.add_argument("--stl")
    args = ap.parse_args(args)

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    recon = _load(os.path.join(repo, "freecad", "reconstruct.py"), "_orion_recon")
    meas = _load(os.path.join(here, "measure_fc.py"), "_orion_measure")

    import FreeCAD as App  # noqa: PLC0415
    import Part  # noqa: PLC0415

    spec = json.load(open(args.spec, encoding="utf-8"))
    os.makedirs(args.workdir, exist_ok=True)

    shapes, per_part, components = [], [], []
    for comp in spec["components"]:
        cid = comp["id"]
        fcstd = os.path.abspath(os.path.join(args.workdir, f"{cid}.FCStd"))

        # Compile through the production path, exactly as a single part is.
        try:
            doc, report = recon.compile_graph(comp["graph"], cid)
            doc.saveAs(fcstd)
            shape = _body_shape(doc, cid)
            placed = _place(shape, comp.get("pos") or [0.0, 0.0, 0.0],
                            comp.get("rot_z", 0.0))
            App.closeDocument(doc.Name)
        except Exception as exc:
            raise _Failed(COMPONENT_FAILED,
                          f"component {cid!r}: {exc}") from exc

        # Measured from the saved document, like a single part, so a component
        # inside an assembly and the same component built alone produce the
        # identical record — including the topology sidecar's authorship map.
        measured = meas.measure_document(fcstd)
        measured["build_report"] = {
            "unsupported": report.get("unsupported", []),
            "recompute_errors": report.get("recompute_errors", []),
            "built": report.get("built", []),
        }
        # Each component as its own mesh, in assembly coordinates.
        #
        # The fused compound STL is one mesh, so a viewer loading it can only
        # ever show the assembly as a single undifferentiated body — no
        # per-part colour, no click-to-select a gear. Exported here because
        # this is the only place the *placed* shapes exist separately; after
        # the fuse below they are welded together and cannot be recovered.
        cstl = os.path.abspath(os.path.join(args.workdir, f"{cid}.stl"))
        try:
            placed.exportStl(cstl)
        except Exception:  # noqa: BLE001 - a preview mesh is not the proof
            cstl = ""

        components.append({"id": cid, "measured": measured, "fcstd": fcstd,
                           "stl": cstl})
        shapes.append(placed)
        per_part.append({"id": cid, "volume": placed.Volume})

    if not shapes:
        raise _Failed(COMPONENT_FAILED, "an assembly needs at least one component")

    try:
        fused = shapes[0]
        for s in shapes[1:]:
            fused = fused.fuse(s)
        fused = fused.removeSplitter()
    except Exception as exc:
        raise _Failed(PLACEMENT_FAILED,
                      f"the components could not be fused: {exc}") from exc

    bb = fused.BoundBox
    out = {
        "components": components,
        "assembly": {
            "parts": per_part,
            "sum_volume": sum(p["volume"] for p in per_part),
            "fused_volume": fused.Volume,
            "solids": len(fused.Solids),
            "watertight": bool(fused.isClosed()),
            "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
        },
    }

    # A compound rather than the fused solid: fusion is the *proof* of
    # non-interference, but it welds distinct components into one shape and
    # loses which solid was which. Downstream wants the parts.
    if args.step:
        try:
            Part.makeCompound(shapes).exportStep(args.step)
            out["assembly"]["step"] = args.step
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            out["assembly"]["step_error"] = str(exc)
    if args.stl:
        try:
            Part.makeCompound(shapes).exportStl(args.stl)
            out["assembly"]["stl"] = args.stl
        except Exception as exc:  # noqa: BLE001
            out["assembly"]["stl_error"] = str(exc)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    print("ok")


def main(argv=None):
    """Run, and turn any failure into a classified record at ``--out``.

    Exits non-zero either way, so a caller that only checks the return code
    still sees a failure; a caller that reads ``--out`` learns which stage.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        _run(argv)
    except _Failed as exc:
        _write_error(argv, exc.reason, exc.detail)
        return 2
    except Exception as exc:  # noqa: BLE001 — anything else is the kernel
        _write_error(argv, PLACEMENT_FAILED, str(exc))
        return 2
    return 0


def _write_error(argv, reason, detail):
    out = None
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    print(reason + ": " + detail, file=sys.stderr)
    if not out:
        return
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"error": {"reason": reason, "detail": detail}}, fh)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
