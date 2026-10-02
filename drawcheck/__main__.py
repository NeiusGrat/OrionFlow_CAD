"""Command line.

    python -m drawcheck check a.pdf [b.pdf ...] [--out DIR] [--vision off|scanned|all] [--json]
    python -m drawcheck stackup "+50 ±0.1" "-20 +0.05/0" [--min 0] [--max 0.5]
    python -m drawcheck sample DIR
    python -m drawcheck bench DIR            # check every PDF in DIR, one summary line each
    python -m drawcheck serve [--port 8010]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print(report) -> None:
    r = report
    print(f"{Path(r.source).name}: {r.count('error')} errors, {r.count('warning')} warnings, "
          f"{r.count('info')} info   [{r.stats.get('annotations')}]")
    for w in r.reader_warnings:
        print(f"    reader  {w}")
    for f in r.findings:
        where = f"p{f.page + 1}" if f.page is not None else "--"
        conf = "" if f.confidence in ("vector", "confirmed", "absence") else f" [{f.confidence}]"
        print(f"    {f.severity:7s} {f.rule} {where:4s} {f.message}{conf}")


def cmd_check(a) -> int:
    from .check import check_file
    from .report import write_annotated_pdf, write_json, write_query_xlsx
    from .store import Store

    store = Store(a.store) if a.store else None
    worst = 0
    for p in a.files:
        report, drawing = check_file(p, vision=a.vision, store=store, customer=a.customer)
        if a.json:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        else:
            _print(report)
        if a.out:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            stem = Path(p).stem
            write_json(report, out / f"{stem}.drawcheck.json")
            write_annotated_pdf(report, p, out / f"{stem}.checked.pdf")
            sizes = {pg.index: (pg.width, pg.height) for pg in drawing.pages}
            write_query_xlsx(report, out / f"{stem}.queries.xlsx", sizes)
            print(f"    -> {out / stem}.checked.pdf, .queries.xlsx, .drawcheck.json")
        worst = max(worst, 2 if report.count("error") else (1 if report.count("warning") else 0))
    return worst


def cmd_stackup(a) -> int:
    from .stackup import link_from_text, stack

    links = [link_from_text(t) for t in a.links]
    r = stack(links, a.min, a.max)
    print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))
    return 0 if r.wc_ok in (None, True) else 1


def cmd_sample(a) -> int:
    from .samples import make_all

    for name, p in make_all(a.dir).items():
        print(f"{name:10s} {p}")
    return 0


def cmd_bench(a) -> int:
    from .check import check_file

    files = sorted(Path(a.dir).rglob("*.pdf"))
    for p in files:
        try:
            r, _ = check_file(p, vision=a.vision)
            print(f"{p.name[:60]:60s} E{r.count('error'):3d} W{r.count('warning'):3d} I{r.count('info'):3d} "
                  f"{r.stats['annotations']}")
        except Exception as e:  # one bad file must not stop a benchmark
            print(f"{p.name[:60]:60s} FAILED {type(e).__name__}: {e}")
    return 0


def cmd_serve(a) -> int:
    import uvicorn

    uvicorn.run("drawcheck.api:app", host=a.host, port=a.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drawcheck")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("files", nargs="+")
    c.add_argument("--out")
    c.add_argument("--vision", default="scanned", choices=["off", "scanned", "all"])
    c.add_argument("--json", action="store_true")
    c.add_argument("--store", help="review database (accepted deviations are suppressed)")
    c.add_argument("--customer", default="")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("stackup")
    s.add_argument("links", nargs="+")
    s.add_argument("--min", type=float)
    s.add_argument("--max", type=float)
    s.set_defaults(fn=cmd_stackup)

    m = sub.add_parser("sample")
    m.add_argument("dir")
    m.set_defaults(fn=cmd_sample)

    b = sub.add_parser("bench")
    b.add_argument("dir")
    b.add_argument("--vision", default="off", choices=["off", "scanned", "all"])
    b.set_defaults(fn=cmd_bench)

    v = sub.add_parser("serve")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8010)
    v.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
