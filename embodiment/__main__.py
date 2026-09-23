"""python -m embodiment build [spec.json | --kind quadruped] OUT_DIR

Builds the robot a spec describes (the default two-link arm when no spec is
given), gates it, and exits non-zero if it was rejected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compiler import compile_robot
from .legged import QuadrupedSpec
from .spec import ArmSpec


def main() -> None:
    ap = argparse.ArgumentParser(prog="embodiment")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("paths", nargs="+", help="[spec.json] OUT_DIR")
    b.add_argument("--kind", choices=["arm", "quadruped"], default="arm",
                   help="the default robot to build when no spec is given")
    a = ap.parse_args()

    spec_path, out = (a.paths[0], a.paths[1]) if len(a.paths) == 2 else (None, a.paths[0])
    if spec_path:
        data = json.loads(Path(spec_path).read_text())
        spec = QuadrupedSpec.model_validate(data) if data.get("kind") == "quadruped" else ArmSpec.model_validate(data)
    else:
        spec = QuadrupedSpec() if a.kind == "quadruped" else ArmSpec()
    report = compile_robot(spec, out)
    for name, g in report["gates"].items():
        print(f"  {'PASS' if g['passed'] else 'FAIL'}  {name}")
    for fmt, r in report["robocheck"].items():
        print(f"  robocheck {fmt}: loaded={r['loaded']} errors={r['errors']} warnings={r['warnings']}")
        for f in r["findings"]:
            print(f"      {f['severity']:7s} {f['code']} {f['where']} {f['message']}")
    print(("ACCEPTED" if report["accepted"] else "REJECTED") + f"  {report['robot']}  "
          f"{report['total_mass_kg'] * 1000:.1f} g  -> {out}")
    sys.exit(0 if report["accepted"] else 1)


if __name__ == "__main__":
    main()
