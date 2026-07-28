"""Does cloud FreeCAD build the same geometry as the FreeCAD that verified the corpus?

The corpus is the parity test. Every record in it is a Blueprint whose frozen,
closed-form predictions were confirmed by FreeCAD 1.1 on Windows. Replay a
sample of them through the deployed Linux container: if its kernel disagrees,
assertions that passed at corpus time now fail, and we learn it here instead of
from a user holding a wrong part.

This matters because conda-forge may not ship 1.1. A different OCC could change
a fillet's volume in the eighth decimal (harmless) or change how a Pocket
resolves (not harmless), and only measurement can tell the two apart.

Usage::

    python deploy/verify_builder.py --n 200
    python deploy/verify_builder.py --n 20 --local     # sanity-check the harness

Exit code is non-zero if any sampled record regresses, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orion.blueprint import Blueprint, BlueprintError  # noqa: E402
from orion.eval_blueprint import extract_blueprint  # noqa: E402
from orion import forge  # noqa: E402
from app.services.blueprint_service import needs_mesh_body  # noqa: E402

DEFAULT_DATA = "data/forge/sft_v1/val.jsonl"


def load_rows(path: str, n: int) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if len(rows) >= n:
                break
            rows.append(json.loads(line))
    return rows


def build_remote(graph: dict, workdir: str,
                 mesh_body: bool = False) -> tuple[dict, dict | None]:
    import modal

    fn = modal.Function.from_name("orionflow-builder", "build_blueprint")
    result = fn.remote(graph, mesh_body)
    for name, blob in (result.get("artifacts") or {}).items():
        if blob:
            with open(os.path.join(workdir, name), "wb") as fh:
                fh.write(blob)
    return result.get("build_log") or {}, result.get("measured")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--local", action="store_true",
                    help="build locally instead of on Modal (harness check)")
    args = ap.parse_args()

    if args.local:
        from app.services.blueprint_service import _build_locally as builder
    else:
        builder = build_remote
        import modal  # noqa: F401 — fail fast if it is missing

        try:
            v = modal.Function.from_name("orionflow-builder", "freecad_version").remote()
            print(f"container FreeCAD version: {v}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not read the container FreeCAD version: {exc}")

    rows = load_rows(args.data, args.n)
    print(f"replaying {len(rows)} verified blueprints "
          f"({'local' if args.local else 'modal'})\n")

    ok = failed = errored = 0
    regressions: list[str] = []
    t0 = time.time()

    for i, row in enumerate(rows):
        completion = row["messages"][-1]["content"]
        try:
            bp = Blueprint.from_dict(extract_blueprint(completion)).freeze()
            graph = bp.resolve()
        except (BlueprintError, ValueError, KeyError, TypeError) as exc:
            errored += 1
            print(f"[{i:3}] PARSE  {exc}")
            continue

        analysis = graph.pop("_analysis", None)
        workdir = tempfile.mkdtemp(prefix="parity_")
        mesh = needs_mesh_body(bp)
        try:
            log, measured = builder(graph, workdir, mesh)
        except Exception as exc:  # noqa: BLE001
            errored += 1
            print(f"[{i:3}] ERROR  {str(exc)[:120]}")
            continue

        if not measured:
            errored += 1
            print(f"[{i:3}] BUILD  rc={log.get('returncode')} "
                  f"{(log.get('stderr') or '')[-120:].strip()}")
            continue

        rows_checked = forge.check_assertions(bp, measured, analysis)
        bad = [r for r in rows_checked if not r.get("passed")]
        if bad:
            failed += 1
            regressions.append(bp.part_class)
            print(f"[{i:3}] FAIL   {bp.part_class}")
            for r in bad[:3]:
                print(f"        {r.get('id')} ({r.get('kind')}): "
                      f"target={r.get('target')} measured={r.get('measured')} "
                      f"rel_err={r.get('rel_err')}")
        else:
            ok += 1
            print(f"[{i:3}] ok     {bp.part_class} "
                  f"({len(rows_checked)} assertions)")

    total = len(rows)
    dt = time.time() - t0
    print(f"\n{'=' * 58}")
    print(f"agreed   : {ok}/{total}")
    print(f"regressed: {failed}")
    print(f"errored  : {errored}")
    print(f"elapsed  : {dt:.1f}s ({dt / max(total, 1):.1f}s/part)")
    if regressions:
        print("\nREGRESSED PART CLASSES (cloud kernel disagrees with the corpus):")
        for c in sorted(set(regressions)):
            print(f"  - {c}")
        print("\nDo not serve Blueprints from this container until this is "
              "understood: the verdicts it produces would not mean what the "
              "corpus proved.")
    return 1 if (failed or errored) else 0


if __name__ == "__main__":
    raise SystemExit(main())
