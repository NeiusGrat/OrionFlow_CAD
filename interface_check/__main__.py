"""Command line.

    python -m interface_check check ASSEMBLY.step [--bom BOM.csv] [--prev OLD.step] [--prev-bom OLD.csv]
                              [--urdf robot.urdf] [--urdf-map map.yaml] [--drawing D.pdf ...]
                              [--datasheet DS.pdf ...] [--vendor-step V.step ...] [--out DIR] [--json]
    python -m interface_check bench [--out DIR]      # seeded-error accuracy run
    python -m interface_check serve [--port 8020]

Exit code: 2 if any high finding, 1 if any medium, else 0.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path


def cmd_check(a) -> int:
    from .pipeline import run_check
    from .report import write_json, write_pdf

    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.step).stem
    r = run_check(a.step, bom=a.bom, prev_step=a.prev, prev_bom=a.prev_bom, urdf=a.urdf, urdf_map=a.urdf_map,
                  drawings=a.drawing, datasheets=a.datasheet, vendor_steps=a.vendor_step,
                  glb=out / f"{stem}.glb" if out else None)
    if a.json:
        print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))
    else:
        d = r.to_dict()
        s = d["summary"]
        print(f"{d['source']['step']}: {s['high']} high, {s['medium']} medium, {s['low']} low, {s['info']} info   "
              f"[{d['stats']['parts']} parts, {d['stats']['instances']} instances, "
              f"{d['stats']['interfaces']} interfaces, {d['stats']['runtime_s']} s]")
        for f in d["findings"]:
            tag = f" [{f['change_status']}]" if f.get("change_status") else ""
            print(f"    {f['severity']:6s} {f['rule_id']}{tag}  {f['message']}")
        for c in d["changes"]:
            print(f"    change {c['part']}: {c['status']} {'; '.join(c['details'][:3])}"
                  + (f"  -> look at {', '.join(c['neighbours'])}" if c["neighbours"] else ""))
        for x in d["assumptions"]:
            print(f"    assume {x}")
    if out:
        write_json(r, out / f"{stem}.interface_check.json")
        write_pdf(r, out / f"{stem}.interface_check.pdf")
        print(f"    -> {out / stem}.interface_check.pdf, .interface_check.json, .glb")
    return 2 if r.count("high") else (1 if r.count("medium") else 0)


def cmd_bench(a) -> int:
    from .bench import main as bench_main
    sys.argv = ["bench", "--out", a.out]
    bench_main()
    return 0


def cmd_serve(a) -> int:
    import uvicorn
    uvicorn.run("interface_check.service.api:app", host=a.host, port=a.port)
    return 0


def main(argv=None) -> int:
    warnings.filterwarnings("ignore", module="build123d")
    ap = argparse.ArgumentParser(prog="interface_check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("step")
    c.add_argument("--bom")
    c.add_argument("--prev")
    c.add_argument("--prev-bom")
    c.add_argument("--urdf")
    c.add_argument("--urdf-map")
    c.add_argument("--drawing", action="append", default=[])
    c.add_argument("--datasheet", action="append", default=[])
    c.add_argument("--vendor-step", action="append", default=[])
    c.add_argument("--out")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_check)
    b = sub.add_parser("bench")
    b.add_argument("--out", default="data/interface_check/bench")
    b.set_defaults(fn=cmd_bench)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8020)
    s.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
