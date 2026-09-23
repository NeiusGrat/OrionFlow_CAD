"""Command line.

    python -m robocheck robot.urdf [more files...] [--json]
    python -m robocheck --robot-descriptions [--only a,b] [--limit N] [--out FILE]

The batch mode checks every model in the `robot_descriptions` package, one
subprocess per model: a model that crashes the MuJoCo compiler, hangs, or
eats memory costs that model, not the run. Results are appended to a JSONL
file and already-checked models are skipped, so an interrupted run resumes.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from .check import check_file

DEFAULT_CACHE = Path("data/robot_descriptions_cache")
DEFAULT_OUT = Path("data/robocheck/robot_descriptions.jsonl")


def _print_report(r: dict) -> None:
    status = "OK " if r["ok"] else ("ERR" if r["loaded"] else "NOLOAD")
    print(f"{status} {r['source']}  errors={r['errors']} warnings={r['warnings']}  {r['stats']}")
    for f in r["findings"]:
        where = f" [{f['where']}]" if f["where"] else ""
        print(f"    {f['severity']:7s} {f['code']}{where} {f['message']}")


def _one_description(name: str) -> dict:
    """Check one robot_descriptions model (runs in the child process)."""
    os.environ.setdefault("ROBOT_DESCRIPTIONS_CACHE", str(DEFAULT_CACHE.resolve()))
    t0 = time.time()
    mod = importlib.import_module(f"robot_descriptions.{name}")
    path = getattr(mod, "MJCF_PATH", None)
    if not path:
        # URDF_PATH directly, or a xacro source rendered to URDF
        from robot_descriptions._xacro import get_urdf_path
        path = get_urdf_path(mod)
    roots = [p for p in (getattr(mod, "REPOSITORY_PATH", None), getattr(mod, "PACKAGE_PATH", None)) if p]
    if getattr(mod, "XACRO_PATH", None):
        # the rendered URDF lives in a cache; relative mesh paths in it are
        # relative to where the xacro source was
        roots.insert(0, os.path.dirname(mod.XACRO_PATH))
    rep = check_file(path, search_roots=roots).to_dict()
    rep["name"] = name
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def _batch(only: list[str] | None, limit: int | None, out: Path, timeout: int) -> None:
    from robot_descriptions._descriptions import DESCRIPTIONS

    names = sorted(only or DESCRIPTIONS)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["name"])
            except Exception:
                pass
    todo = [n for n in names if n not in done][: limit or None]
    print(f"{len(names)} models, {len(done & set(names))} already checked, {len(todo)} to run -> {out}")
    env = dict(os.environ)
    env.setdefault("ROBOT_DESCRIPTIONS_CACHE", str(DEFAULT_CACHE.resolve()))
    # xacro reads the YAML it includes with the platform codepage unless told
    # otherwise; on Windows that is cp1252 and a UTF-8 file fails to expand.
    env["PYTHONUTF8"] = "1"
    for i, name in enumerate(todo, 1):
        t0 = time.time()
        try:
            # The child runs with PYTHONUTF8, so read it as UTF-8; replace what
            # does not decode rather than lose the whole batch to one byte.
            proc = subprocess.run([sys.executable, "-m", "robocheck", "--one-description", name],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, env=env)
            line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("{")), None)
            rec = json.loads(line) if line else {
                "name": name, "loaded": False, "ok": False, "errors": 1, "warnings": 0, "stats": {},
                "findings": [{"code": "RUN001", "severity": "error", "where": "",
                              "message": "checker crashed: " + ((proc.stderr or "").strip().splitlines() or ["?"])[-1][:300],
                              "value": None}]}
        except subprocess.TimeoutExpired:
            rec = {"name": name, "loaded": False, "ok": False, "errors": 1, "warnings": 0, "stats": {},
                   "findings": [{"code": "RUN002", "severity": "error", "where": "",
                                 "message": f"timed out after {timeout} s", "value": None}]}
        rec.setdefault("seconds", round(time.time() - t0, 1))
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        codes = Counter(f["code"] for f in rec["findings"] if f["severity"] != "info")
        print(f"[{i}/{len(todo)}] {name:40s} {'OK ' if rec['ok'] else 'ERR'} "
              f"e={rec['errors']} w={rec['warnings']} {dict(codes)} {rec['seconds']}s", flush=True)
    summarise(out)


def summarise(out: Path) -> dict:
    recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    infra = {"RUN001", "RUN002"}
    checked = [r for r in recs if not ({f["code"] for f in r["findings"]} & infra)]
    by_code: Counter = Counter()
    models_by_code: Counter = Counter()
    for r in checked:
        cs = [f["code"] for f in r["findings"] if f["severity"] != "info"]
        by_code.update(cs)
        models_by_code.update(set(cs))
    s = {
        "models": len(recs),
        "checked": len(checked),
        "could_not_run": len(recs) - len(checked),
        "loaded": sum(r["loaded"] for r in checked),
        "clean": sum(r["ok"] and r["warnings"] == 0 for r in checked),
        "with_errors": sum(r["errors"] > 0 for r in checked),
        "with_warnings_only": sum(r["errors"] == 0 and r["warnings"] > 0 for r in checked),
        "models_by_finding": dict(models_by_code.most_common()),
        "findings_by_code": dict(by_code.most_common()),
    }
    (out.parent / (out.stem + "_summary.json")).write_text(json.dumps(s, indent=1))
    print(json.dumps(s, indent=1))
    return s


def main() -> None:
    ap = argparse.ArgumentParser(prog="robocheck", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--json", action="store_true", help="print JSON reports")
    ap.add_argument("--robot-descriptions", action="store_true", help="check every robot_descriptions model")
    ap.add_argument("--only", help="comma-separated robot_descriptions names")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--summary", action="store_true", help="summarise an existing results file")
    ap.add_argument("--one-description", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.one_description:
        print(json.dumps(_one_description(a.one_description)))
        return
    if a.summary:
        summarise(a.out)
        return
    if a.robot_descriptions:
        _batch(a.only.split(",") if a.only else None, a.limit, a.out, a.timeout)
        return
    if not a.files:
        ap.error("give one or more files, or --robot-descriptions")
    failed = False
    for f in a.files:
        r = check_file(f).to_dict()
        print(json.dumps(r)) if a.json else _print_report(r)
        failed |= not r["ok"]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
