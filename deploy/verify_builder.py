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
from orion_physical_ai import verify  # noqa: E402
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
        else:
            # A pin that is never read is a comment. The image declares a
            # version; this asserts the container actually has it, so a resolver
            # change or a stale image surfaces here rather than as unexplained
            # geometry drift in the numbers this script produces.
            from deploy.modal_builder import FREECAD_VERSION

            got = ".".join(str(p) for p in (v.get("version") or [])[:3])
            if got != FREECAD_VERSION:
                print(f"WARNING: container runs FreeCAD {got}, but the image "
                      f"pins {FREECAD_VERSION} — results are not comparable "
                      f"with anything measured on the pinned kernel")

    rows = load_rows(args.data, args.n)
    print(f"replaying {len(rows)} verified blueprints "
          f"({'local' if args.local else 'modal'})\n")

    ok = failed = errored = kernel_only = 0
    regressions: list[str] = []
    reclassified: list[str] = []
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
        # The assertions are only half of what VERIFIED now means. Since
        # 2026-08-05 the kernel's own opinion of the shape counts too, so a
        # harness that scored assertions alone would report the old definition
        # while production served the new one.
        bad_kernel = [
            c for c in verify.solid_validity_checks(measured)
            if c["status"] == verify.FAIL
        ]
        if bad:
            failed += 1
            regressions.append(bp.part_class)
            print(f"[{i:3}] FAIL   {bp.part_class}")
            for r in bad[:3]:
                print(f"        {r.get('id')} ({r.get('kind')}): "
                      f"target={r.get('target')} measured={r.get('measured')} "
                      f"rel_err={r.get('rel_err')}")
        elif bad_kernel:
            # Passed every assertion it was graded on and still is not a sound
            # solid. This is the population the stricter gate reclassifies, and
            # it is counted apart from a genuine kernel regression because the
            # cause is different: the corpus accepted these, the gate no longer
            # does.
            kernel_only += 1
            reclassified.append(bp.part_class)
            print(f"[{i:3}] SOLID  {bp.part_class} — "
                  + "; ".join(c["detail"] for c in bad_kernel))
        else:
            ok += 1
            print(f"[{i:3}] ok     {bp.part_class} "
                  f"({len(rows_checked)} assertions"
                  f"{', solid sound' if measured.get('valid') is not None else ''})")

    total = len(rows)
    dt = time.time() - t0
    print(f"\n{'=' * 58}")
    print(f"verified   : {ok}/{total}      (assertions AND a sound solid)")
    print(f"unsound    : {kernel_only}"
          f"       (assertions agreed, the solid did not)")
    print(f"regressed  : {failed}")
    print(f"errored    : {errored}")
    print(f"elapsed    : {dt:.1f}s ({dt / max(total, 1):.1f}s/part)")
    print(f"\nunder the pre-2026-08-05 definition this sample would score "
          f"{ok + kernel_only}/{total}.")
    if reclassified:
        print("\nRECLASSIFIED BY THE SOLID GATE (these were VERIFIED before):")
        for c in sorted(set(reclassified)):
            print(f"  - {c}")
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
