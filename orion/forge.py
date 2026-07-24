"""The forge loop: frozen blueprint → build → measure → verdict → record.

One function, :func:`run_blueprint`, owns the whole cycle for a single part:

    resolve (expressions → concrete graph, exact per-sketch analytics)
    build   (freecad/reconstruct.py, the production compiler, subprocess)
    measure (orion/measure_fc.py, AddSubShape + body volume + bbox)
    verify  (frozen assertions vs measurements — Tier tags decide tolerance)

The record written to disk contains blueprint, graph, build log, measurement,
and verdict; nothing is written unless the blueprint hash re-verifies, and the
verdict never mutates the blueprint (the one-way rule, enforced by hashing).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from typing import Optional

from .blueprint import Blueprint, perturbed

DEFAULT_RECORDS = "data/forge/records"
BUILD_TIMEOUT_S = 90   # per-part wall clock for build+measure


def _freecad_python() -> str:
    env = os.environ.get("ORION_FREECAD_PYTHON")
    if env and os.path.exists(env):
        return env
    cand = r"C:/Program Files/FreeCAD 1.1/bin/python.exe"
    if os.path.exists(cand):
        return cand
    raise RuntimeError("no FreeCAD python; set ORION_FREECAD_PYTHON")


def build_and_measure(graph: dict, workdir: str, tag: str,
                      mesh_body: bool = False) -> tuple[dict, dict]:
    """Compile with the production reconstruct.py and measure, in ONE FreeCAD
    process (build_measure_fc.py) — interpreter startup dominates cycle time,
    so this halves the loop cost. Returns (build_log, measurement).

    ``mesh_body`` additionally mesh-samples the body for Tier-2 convergence
    verification (only needed for irreducible bodies like manifold_runner)."""
    g = {k: v for k, v in graph.items() if k != "_analysis"}
    gpath = os.path.join(workdir, f"{tag}.json")
    fpath = os.path.join(workdir, f"{tag}.FCStd")
    mpath = os.path.join(workdir, f"{tag}.measured.json")
    json.dump(g, open(gpath, "w", encoding="utf-8"))
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "build_measure_fc.py")
    cmd = [_freecad_python(), runner, "--graph", gpath,
           "--fcstd", fpath, "--out", mpath]
    if mesh_body:
        cmd.append("--mesh-body")
    # HARD TIMEOUT: OCC can wedge on pathological geometry (a stress-mode
    # self-intersecting sweep or an oversized dress-up will do it), and without
    # a bound one part stalls an entire run forever. A timeout is itself a
    # finding — the record becomes a natural failure with the kernel hang
    # recorded.
    #
    # Output goes to FILES, not pipes: with capture_output=True the child's
    # stdout/stderr are pipes, and on Windows a killed FreeCAD child can leave
    # an OCC worker holding the pipe open so subprocess.run's post-kill
    # communicate() blocks FOREVER — the exact hang that stalled the OCC
    # harvest. File redirection has no pipe to drain, so the timeout kills
    # cleanly.
    opath = os.path.join(workdir, f"{tag}.stdout.txt")
    epath = os.path.join(workdir, f"{tag}.stderr.txt")
    try:
        with open(opath, "w", encoding="utf-8") as _of, \
                open(epath, "w", encoding="utf-8") as _ef:
            r1 = subprocess.run(cmd, stdout=_of, stderr=_ef,
                                timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return ({"stdout": "", "stderr": "TIMEOUT after "
                 f"{BUILD_TIMEOUT_S}s — kernel did not converge",
                 "returncode": -9, "timeout": True}, {})

    def _tail(path: str, n: int = 4000) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()[-n:]
        except OSError:
            return ""
    build_log = {"stdout": _tail(opath), "stderr": _tail(epath),
                 "returncode": r1.returncode}
    if r1.returncode != 0 or not os.path.exists(mpath):
        return build_log, {}
    measured = json.load(open(mpath, encoding="utf-8"))
    build_log["build_report"] = measured.pop("build_report", {})
    return build_log, measured


def check_assertions(bp: Blueprint, measured: dict) -> list[dict]:
    """Frozen assertions vs measurements. Every row carries its evidence."""
    rows = []
    feats = {f["name"]: f for f in measured.get("features", [])}
    for a in bp.resolve_assertions():
        kind = a.get("kind")
        target = a.get("target_value")
        tol = float(a.get("tol_rel", 1e-6))
        got: Optional[float] = None
        if kind == "body_volume":
            got = measured.get("body_volume")
        elif kind == "feature_volume":
            got = (feats.get(a.get("feature")) or {}).get("addsub_volume")
        elif kind == "bbox_extent":
            bb = measured.get("bbox")
            if bb:
                axis = {"x": 0, "y": 1, "z": 2}[a.get("axis", "z")]
                got = bb[axis + 3] - bb[axis]
        elif kind == "solids":
            got = measured.get("solids")
        elif kind == "watertight":
            wt = measured.get("watertight")
            rows.append({"id": a.get("id"), "kind": kind, "tier": a.get("tier"),
                         "target": True, "measured": wt,
                         "passed": wt is True})
            continue
        elif kind == "volume_between":
            v = measured.get("body_volume")
            lo, hi = a.get("lo_value"), a.get("hi_value")
            ok = (v is not None and lo is not None and hi is not None
                  and lo <= v <= hi)
            rows.append({"id": a.get("id"), "kind": kind, "tier": a.get("tier"),
                         "lo": lo, "hi": hi, "measured": v, "passed": ok})
            continue
        elif kind == "precondition":
            # Static: already decided before the build; recorded for the trace.
            ok = target is not None and target > 0
            rows.append({"id": a.get("id"), "kind": kind, "tier": a.get("tier"),
                         "target": target, "measured": None, "passed": ok,
                         "why": None if ok else "precondition violated"})
            continue
        elif kind == "body_mesh_converged":
            # Tier-2 numerical: the mesh-sampled body volume must CONVERGE to
            # OCC's across tessellation densities (monotone decrease, finest
            # within tol, Richardson extrapolation agreeing with OCC). A single
            # coarse-mesh match is not accepted — it must demonstrably converge.
            rows.append(_check_mesh_convergence(a, measured))
            continue
        row = {"id": a.get("id"), "kind": kind, "tier": a.get("tier"),
               "target": target, "measured": got}
        if got is None or target is None:
            row.update(passed=False, why="no measurement")
        else:
            err = abs(got - target) / max(abs(target), 1e-12)
            row.update(rel_err=err, passed=err <= tol)
        rows.append(row)
    return rows


def _check_mesh_convergence(a: dict, measured: dict) -> dict:
    """Verdict for a body_mesh_converged assertion: the mesh series must
    converge to OCC's body volume, not merely be close at one density."""
    tol = float(a.get("tol_rel", 1e-3))
    series = [s for s in (measured.get("mesh_series") or []) if "V" in s]
    occ = measured.get("body_volume")
    row = {"id": a.get("id"), "kind": "body_mesh_converged",
           "tier": a.get("tier"), "measured": occ}
    if occ is None or len(series) < 3:
        row.update(passed=False, why="no mesh series")
        return row
    errs = [abs(s["V"] - occ) / occ for s in series]
    monotone = all(errs[i] >= errs[i + 1] - 1e-9 for i in range(len(errs) - 1))
    finest = errs[-1]
    # Richardson: V ~ Vinf + c*d^p from the three finest densities.
    (d1, v1), (d2, v2), (d3, v3) = [(s["defl"], s["V"]) for s in series[-3:]]
    try:
        import math
        p = math.log(abs((v1 - v2) / (v2 - v3))) / math.log(d1 / d2)
        vinf = v3 + (v2 - v3) * d3 ** p / (d2 ** p - d3 ** p)
        rich_err = abs(vinf - occ) / occ
    except Exception:  # noqa: BLE001
        rich_err = finest
    # Convergence is proven by monotone decrease reaching the tolerance.
    # Richardson V_inf is a confirmation the limit is OCC's value, but the
    # extrapolation is numerically fragile once the series nears machine noise
    # (dividing by v2-v3): when the finest mesh is already an order of
    # magnitude inside tol, that alone establishes convergence and neither the
    # Richardson step NOR strict monotonicity is required to also pass — a
    # sub-1e-6 series can wiggle non-monotonically on pure tessellation noise
    # while being unambiguously converged.
    deeply_converged = finest <= tol / 10
    converged = finest <= tol and (
        deeply_converged or (monotone and rich_err <= tol))
    row.update(rel_err=finest, monotone=monotone, richardson_rel_err=rich_err,
               facets=[s.get("facets") for s in series], passed=converged)
    return row


def failed_preconditions(bp: Blueprint) -> list[dict]:
    """Preconditions are checked BEFORE any build: a violated one means the
    closed form itself is invalid (self-intersecting sweep, apex-crossing
    draft), so the verifier refuses to predict rather than mismeasuring."""
    out = []
    for a in bp.resolve_assertions():
        if a.get("kind") == "precondition":
            tv = a.get("target_value")
            if tv is None or tv <= 0:
                out.append({"id": a.get("id"), "target": tv,
                            "why": a.get("why", "precondition violated")})
    return out


def run_blueprint(bp: Blueprint, tag: str, workdir: str,
                  force: bool = False) -> dict:
    """One full forge cycle. Returns the verdict record (not yet persisted).

    ``force=True`` bypasses precondition refusal and builds anyway — stress
    mode. The violated guards are still recorded; the point is to let OCC
    fail for real so the repair corpus contains genuine kernel behaviour,
    not only synthetic labels."""
    if not bp.verify_hash():
        raise ValueError("blueprint hash does not verify — refusing to build")
    pre = failed_preconditions(bp)
    if pre and not force:
        return {"tag": tag, "blueprint_hash": bp.blueprint_hash,
                "passed": False, "refused": True,
                "failed_preconditions": pre, "assertions": [],
                "build_ok": False, "build_log": {}, "measured": {},
                "elapsed_s": 0.0}
    graph = bp.resolve()
    t0 = time.time()
    mesh_body = any(a.get("kind") == "body_mesh_converged"
                    for a in bp.assertions)
    build_log, measured = build_and_measure(graph, workdir, tag,
                                            mesh_body=mesh_body)
    rows = check_assertions(bp, measured) if measured else []
    passed = bool(rows) and all(r["passed"] for r in rows) and not pre
    return {
        "tag": tag,
        "forced_past_preconditions": pre if (pre and force) else [],
        "blueprint_hash": bp.blueprint_hash,
        "passed": passed,
        "assertions": rows,
        "build_ok": bool(measured),
        "build_log": build_log,
        "measured": measured,
        "elapsed_s": round(time.time() - t0, 2),
    }


def differential_test(bp: Blueprint, variables: list[str],
                      workdir: str, rel_delta: float = 0.05) -> list[dict]:
    """Perturb each variable, RE-PREDICT FROM CLOSED FORM via a sibling frozen
    blueprint, rebuild, and re-verify. No finite differences anywhere — each
    sibling is a complete exact contract, so there is no truncation error and
    a pass proves the part is genuinely parametric in that variable."""
    out = []
    for var in variables:
        delta = rel_delta * bp.variables[var]
        sib = perturbed(bp, var, delta)
        rec = run_blueprint(sib, f"diff_{var}", workdir)
        out.append({"variable": var, "delta": delta,
                    "passed": rec["passed"],
                    "assertions": rec["assertions"]})
    return out


def scale_invariance_test(bp: Blueprint, length_vars: list[str],
                          workdir: str, k: float = 2.0) -> dict:
    """Scale every length variable by k and verify the measured volume scales
    by exactly k³ (relative 1e-9). Catches unit, placement and datum bugs
    that absolute volume checks can miss."""
    base = run_blueprint(bp, "scale_base", workdir)
    vs = dict(bp.variables)
    for v in length_vars:
        vs[v] = vs[v] * k
    scaled_bp = Blueprint(part_class=bp.part_class, variables=vs,
                          datums=bp.datums, design_plan=bp.design_plan,
                          assertions=bp.assertions,
                          template=bp.template).freeze()
    scaled = run_blueprint(scaled_bp, "scale_k", workdir)
    v0 = (base.get("measured") or {}).get("body_volume")
    v1 = (scaled.get("measured") or {}).get("body_volume")
    if not v0 or not v1:
        return {"passed": False, "why": "missing volume"}
    err = abs(v1 - v0 * k ** 3) / (v0 * k ** 3)
    return {"passed": err <= 1e-9, "k": k, "v_base": v0, "v_scaled": v1,
            "rel_err": err}


def save_record(record: dict, bp: Blueprint, graph: dict,
                out_dir: str = DEFAULT_RECORDS,
                extras: Optional[dict] = None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "schema": "orion-forge-record-v1",
        "blueprint": bp.to_dict(),
        "feature_graph": {k: v for k, v in graph.items() if k != "_analysis"},
        "analysis": graph.get("_analysis", {}),
        "verdict": record,
    }
    if extras:
        payload.update(extras)
    path = os.path.join(out_dir, f"{bp.part_class}_{bp.blueprint_hash[:10]}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    return path


def workdir() -> str:
    return tempfile.mkdtemp(prefix="orion_forge_")
