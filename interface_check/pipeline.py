"""run_check(step, bom, prev_step, urdf, ...) -> Report, as fifteen recorded stages.

    01 file_validation        02 complexity            03 geometry_extraction
    04 part_identification    05 assembly_structure    06 interface_detection
    07 clearance_collision    08 bom_consistency       09 drawing_consistency
    10 revision_comparison    11 gdt_dimensions        12 robot_model
    13 manufacturing          14 evidence              15 final_report

Every stage records status (PASS / FAIL / WARNING / SKIPPED / ERROR), duration,
peak memory and the checks it ran, so a slow or failing job says where.
Stages 01-06 are core: their failure ends the run with a typed
:class:`AnalysisError`. Every later stage is optional: an exception there is
recorded as that stage's ERROR and the report is still produced.

Geometry first, AI last: everything up to stage 13 is deterministic code. The
LLM is asked only for BOM leftovers (08), drawing part numbers (09) and the
plain-language narrative (14), and the narrative may only cite findings that
exist.
"""
from __future__ import annotations

import gc
import os
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .bom import BomResult, read_bom, reconcile
from .cache import FeatureCache, NoCache
from .components.library import Library
from .errors import AnalysisError
from .ingest_step import StepReadError, read_assembly
from .inspect_step import Complexity, inspect
from .interfaces import MAX_INSTANCES, Contact, find_contacts, graph
from .limits import Limits, limits_for
from .llm import LLM, LLMUnavailable, NoLLM, from_env, match_bom
from .models import SEVERITIES, Features, Finding, Instance, Part, Report
from .rules.checks import Checker
from .version import ENGINE_VERSION

STAGES = [
    ("01", "file_validation"), ("02", "complexity"), ("03", "geometry_extraction"),
    ("04", "part_identification"), ("05", "assembly_structure"), ("06", "interface_detection"),
    ("07", "clearance_collision"), ("08", "bom_consistency"), ("09", "drawing_consistency"),
    ("10", "revision_comparison"), ("11", "gdt_dimensions"), ("12", "robot_model"),
    ("13", "manufacturing"), ("14", "evidence"), ("15", "final_report"),
]
CORE = {"file_validation", "complexity", "geometry_extraction", "part_identification",
        "assembly_structure", "interface_detection"}
#: which rules each stage owns, so a stage's PASS/FAIL comes from its own findings
STAGE_RULES = {
    "file_validation": {"PART_INVALID"},
    "complexity": {"UNSUPPORTED_GEOMETRY"},
    "assembly_structure": {"ASSEMBLY_STRUCTURE_MISSING"},
    "part_identification": {"COMPONENT_UNCONFIRMED"},
    "interface_detection": {"HOLE_MISALIGNED", "HOLE_MISSING", "PATTERN_MISMATCH", "FASTENER_SIZE_MISMATCH",
                            "BEARING_SEAT", "MOTOR_FLANGE"},
    "clearance_collision": {"INTERFERENCE"},
    "bom_consistency": {"BOM_QTY_MISMATCH", "IN_CAD_NOT_BOM", "IN_BOM_NOT_CAD", "LOW_CONFIDENCE_MATCH"},
    "drawing_consistency": {"DRAWING_STALE", "DRAWING_REV_MISMATCH", "DRAWING_UNMATCHED", "DATASHEET_NEEDS_REVIEW"},
    "robot_model": {"URDF_MASS_DRIFT", "URDF_COM_DRIFT", "JOINT_AXIS_DRIFT", "JOINT_ORIGIN_DRIFT",
                    "URDF_LINK_UNMAPPED", "URDF_MESH_MISSING"},
}


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2**20
    except Exception:  # noqa: BLE001 - memory reporting is best effort
        return 0.0


class Stages:
    """Records each stage; ``progress`` is called on every transition (worker heartbeat)."""

    def __init__(self, progress: Callable[[str, dict], None] | None = None):
        self.records: dict[str, dict] = {}
        self.progress = progress or (lambda stage, info: None)
        self.peak_mb = 0.0

    @contextmanager
    def stage(self, name: str):
        sid = dict((n, i) for i, n in STAGES)[name]
        rec = {"stage_id": sid, "stage": name, "status": "RUNNING", "started": time.time()}
        self.records[name] = rec
        self.progress(name, {"status": "RUNNING"})
        t0, m0 = time.time(), _rss_mb()
        try:
            yield rec
        except AnalysisError as e:
            e.stage = e.stage or name
            rec.update(status="ERROR", reason=str(e), failure_code=e.code)
            raise
        except Exception as e:  # noqa: BLE001
            rec.update(status="ERROR", reason=f"{type(e).__name__}: {e}", trace=traceback.format_exc(limit=3))
            if name in CORE:
                raise
        finally:
            rss = _rss_mb()
            self.peak_mb = max(self.peak_mb, rss, m0)
            rec.update(duration_s=round(time.time() - t0, 3), rss_mb=round(rss, 1))
            if rec["status"] == "RUNNING":
                rec["status"] = "DONE"
            self.progress(name, {"status": rec["status"], "duration_s": rec["duration_s"]})

    def skip(self, name: str, reason: str) -> None:
        sid = dict((n, i) for i, n in STAGES)[name]
        self.records[name] = {"stage_id": sid, "stage": name, "status": "SKIPPED", "reason": reason}

    def finalize(self, findings: list[Finding]) -> list[dict]:
        by_rule: dict[str, list[Finding]] = {}
        for f in findings:
            by_rule.setdefault(f.rule_id, []).append(f)
        out = []
        for sid, name in STAGES:
            rec = self.records.get(name) or {"stage_id": sid, "stage": name, "status": "SKIPPED",
                                              "reason": "no input for this stage"}
            if name == "final_report" and rec["status"] == "DONE":
                rec["status"] = "PASS"
            if rec["status"] == "DONE":
                mine = [f for r in STAGE_RULES.get(name, ()) for f in by_rule.get(r, [])]
                worst = min((SEVERITIES.index(f.severity) for f in mine), default=None)
                rec["status"] = ("PASS" if worst is None else "FAIL" if worst <= 1 else "WARNING")
                rec["findings"] = [f.fingerprint for f in mine]
                rec["checks"] = sorted(STAGE_RULES.get(name, ()))
            rec["engine_version"] = ENGINE_VERSION
            rec.pop("started", None)
            out.append(rec)
        return out


@dataclass
class Analysis:
    path: Path
    parts: dict[str, Part]
    instances: list[Instance]
    part_feats: dict[str, Features]
    feats: dict[str, Features]                  # per instance, assembly frame
    contacts: list[Contact]
    findings: list[Finding]
    part_names: dict[str, str]                  # instance_id -> part name
    checker: Checker | None = None
    timings: dict = field(default_factory=dict)
    part_hashes: dict = field(default_factory=dict)
    contact_stats: dict = field(default_factory=dict)

    def graph(self) -> dict[str, set[str]]:
        return graph(self.contacts)

    def release(self) -> None:
        """Drop every B-rep reference so the kernel's memory can be reclaimed."""
        for p in self.parts.values():
            p.shape = None
        for i in self.instances:
            i.shape = None
            i.loc = None
        for f in list(self.part_feats.values()) + list(self.feats.values()):
            for pf in f.planes:
                pf.face = None
        self.contacts = []
        self.checker = None
        gc.collect()


def gate(step: str | Path, limits: Limits) -> Complexity:
    """Stages 01-02 on the raw file: refuse what cannot or must not be analysed."""
    step = Path(step)
    size_mb = step.stat().st_size / 2**20
    if size_mb > limits.max_file_mb:
        raise AnalysisError("FILE_TOO_LARGE", f"{size_mb:.0f} MB exceeds the {limits.max_file_mb} MB limit")
    c = inspect(step)
    for p in c.problems:
        code = p.split(":", 1)[0]
        raise AnalysisError(code, p.split(":", 1)[1].strip())
    if c.face_count > limits.max_faces:
        raise AnalysisError("TOO_MANY_FACES", f"{c.face_count:,} faces exceeds the {limits.max_faces:,} limit")
    if c.triangle_loops > limits.max_triangles:
        raise AnalysisError("TOO_MANY_FACES", f"{c.triangle_loops:,} mesh triangles exceeds the "
                            f"{limits.max_triangles:,} limit")
    if c.part_count > limits.max_parts:
        raise AnalysisError("TOO_MANY_PARTS", f"{c.part_count:,} parts exceeds the {limits.max_parts:,} limit")
    return c


def analyse(step: str | Path, library: Library | None = None, cache: FeatureCache | None = None,
            limits: Limits | None = None, stages: Stages | None = None, workdir: str | Path | None = None
            ) -> Analysis:
    limits = limits or limits_for(os.environ.get("IC_PLAN", "free"))
    cache = cache or NoCache()
    st = stages or Stages()
    t: dict = {}
    with st.stage("geometry_extraction") as rec:
        t0 = time.time()
        try:
            parts, instances, findings = read_assembly(step)
        except StepReadError as e:
            raise AnalysisError("INVALID_STEP", str(e)) from e
        if len(instances) > min(limits.max_instances, MAX_INSTANCES * 100):
            raise AnalysisError("TOO_MANY_PARTS", f"{len(instances):,} instances exceeds the "
                                f"{limits.max_instances:,} limit")
        if not any(p.valid for p in parts.values()):
            raise AnalysisError("GEOMETRY_INVALID", "no part in the file has a valid solid body")
        t["ingest_s"] = time.time() - t0
        t0 = time.time()
        part_feats: dict[str, Features] = {}
        hashes: dict[str, str] = {}
        for pid, p in parts.items():
            part_feats[pid], hashes[pid] = cache.features(p.shape, workdir)
        feats = {i.instance_id: part_feats[i.part_id].moved(i.transform, i.loc) for i in instances}
        t["features_s"] = time.time() - t0
        rec["measurements"] = {"parts": len(parts), "instances": len(instances),
                               "cache_hits": cache.hits, "cache_misses": cache.misses}
    names = {i.instance_id: parts[i.part_id].name for i in instances}

    with st.stage("complexity") as rec:
        mesh_parts = [pid for pid, f in part_feats.items() if f.is_mesh]
        for pid in mesh_parts:
            f = part_feats[pid]
            paths = [i.path for i in instances if i.part_id == pid]
            findings.append(Finding(
                "UNSUPPORTED_GEOMETRY", "info", paths[:10],
                f"{parts[pid].name} appears to be a triangulated mesh stored in STEP ({f.face_count:,} faces, "
                f"{f.triangle_count:,} triangles). Hole, contact, interference and component checks were "
                "skipped for it; mass, bounding box, BOM and adjacency still apply.",
                measured={"faces": f.face_count, "triangles": f.triangle_count, "geometry_type": "MESH"},
                parts=[parts[pid].name], method="per-face surface type and edge count"))
        # A mesh rebuilt from triangles is rarely a watertight solid; its BRepCheck
        # failure is expected, not a design defect of the part.
        mesh_names = {parts[pid].name for pid in mesh_parts}
        for f in findings:
            if f.rule_id == "PART_INVALID" and set(f.parts) <= mesh_names:
                f.severity = "low"
                f.message += " (Expected for a triangulated mesh; it is used for mass and adjacency only.)"
        if mesh_parts and len(mesh_parts) == len(part_feats):
            raise AnalysisError("UNSUPPORTED_MESH", "every body in the assembly is a triangulated mesh")
        rec["measurements"] = {"mesh_parts": len(mesh_parts), "brep_parts": len(part_feats) - len(mesh_parts)}

    with st.stage("assembly_structure") as rec:
        rec["measurements"] = {"instances": len(instances), "parts": len(parts)}

    checker = Checker(instances, feats, [], names, library)
    with st.stage("part_identification") as rec:
        checker.match_components()
        rec["measurements"] = {"library_matches": len(checker.matches)}

    with st.stage("interface_detection") as rec:
        t0 = time.time()
        cstats: dict = {}
        contacts = find_contacts(instances, feats, cstats)
        checker.contacts = contacts
        t["interfaces_s"] = time.time() - t0
        t0 = time.time()
        for c in contacts:
            checker.check_joint(c)
        checker.check_bearings()
        checker.check_motors()
        t["checks_s"] = time.time() - t0
        rec["measurements"] = {"contacts": len(contacts), "adjacency_only": sum(not c.exact for c in contacts),
                               **cstats}
    with st.stage("clearance_collision") as rec:
        checker.check_interference()
        rec["measurements"] = {"skipped": dict(checker.skipped)}
    findings += checker.findings
    return Analysis(Path(step), parts, instances, part_feats, feats, contacts, findings, names, checker,
                    {k: round(v, 3) for k, v in t.items()}, hashes, cstats)


def _cache_stats(hits: int, misses: int) -> dict:
    n = hits + misses
    return {"hits": hits, "misses": misses, "hit_rate": round(hits / n, 4) if n else 0.0}


def _llm_matcher(llm: LLM, notes: list[str]):
    def run(rows, cad_names):
        try:
            return match_bom(llm, rows, cad_names)
        except LLMUnavailable as e:
            notes.append(f"BOM: {len(rows)} row(s) left after exact and fuzzy matching were not sent to an "
                         f"LLM ({e}); they are reported as unmatched")
            return []
    return run


def run_check(step: str | Path, bom: str | Path | None = None, prev_step: str | Path | None = None,
              urdf: str | Path | None = None, urdf_map: str | Path | None = None,
              drawings: list[str | Path] = (), datasheets: list[str | Path] = (),
              vendor_steps: list[str | Path] = (), llm: LLM | None = None,
              library: Library | None = None, prev_bom: str | Path | None = None,
              glb: str | Path | None = None, cache: FeatureCache | None = None,
              limits: Limits | None = None, progress: Callable[[str, dict], None] | None = None,
              workdir: str | Path | None = None) -> Report:
    t_start = time.time()
    llm = llm if llm is not None else from_env()
    library = library or Library()
    limits = limits or limits_for(os.environ.get("IC_PLAN", "free"))
    cache = cache or NoCache()
    hits0, misses0 = cache.hits, cache.misses
    st = Stages(progress)
    notes: list[str] = []

    with st.stage("file_validation") as rec:
        complexity = gate(step, limits)
        rec["measurements"] = complexity.to_dict()

    # Vendor STEP / datasheets extend the library the interface rules use.
    extra_findings: list[Finding] = []
    if vendor_steps or datasheets:
        from .components.datasheet import read_pdf, spec_from_step
        for v in vendor_steps:
            library.add(spec_from_step(v))
        for d in datasheets:
            try:
                c = read_pdf(d, llm)
            except LLMUnavailable as e:
                notes.append(str(e))
                continue
            library.add(c)
            if c.needs_review:
                extra_findings.append(Finding(
                    "DATASHEET_NEEDS_REVIEW", "info", [], f"{Path(d).name}: values {', '.join(c.needs_review)} "
                    "were read by the model but do not appear in the PDF text; confirm them before relying on them.",
                    parts=[c.name], source="llm", method="datasheet text-layer number guard"))

    a = analyse(step, library, cache, limits, st, workdir)
    report = Report(source={"step": Path(step).name, "bom": Path(bom).name if bom else None,
                            "prev_step": Path(prev_step).name if prev_step else None,
                            "urdf": Path(urdf).name if urdf else None, "llm": llm.name})
    report.findings = list(a.findings) + extra_findings
    report.assumptions += ["Fastener and bearing checks compare nominal sizes; STEP carries no thread or fit class"]
    if a.contact_stats.get("capped"):
        notes.append(f"Contact search: {a.contact_stats['capped']} candidate face pairs beyond "
                     "the per-pair cap were not measured exactly (largest faces were kept)")
    for what, n in (a.checker.skipped.items() if a.checker else []):
        notes.append(f"Skipped {what}: {n}")

    bom_result: BomResult | None = None
    rows = []
    if bom:
        with st.stage("bom_consistency") as rec:
            rows = read_bom(bom)
            bom_result = reconcile(rows, a.parts, a.instances, _llm_matcher(llm, notes))
            report.findings += bom_result.findings
            report.bom = {"rows": [r.to_dict() for r in rows],
                          "matches": [{"row": i, "part": a.parts[pid].name, "how": bom_result.how[i]}
                                      for i, pid in bom_result.pairs.items()]}
            rec["measurements"] = {"rows": len(rows), "matched": len(bom_result.pairs)}

    if urdf:
        with st.stage("robot_model") as rec:
            from .urdf_drift import DEFAULT_DENSITY, density_for
            from .urdf_drift import check as urdf_check
            mats = bom_result.materials if bom_result else {}
            dens, known = {}, {}
            for i in a.instances:
                rho = density_for(mats.get(i.part_id, ""))
                dens[i.instance_id] = (rho, False) if rho else (DEFAULT_DENSITY, True)
                m = a.checker.matches.get(i.instance_id) if a.checker else None
                if m and m.component.mass_kg:
                    known[i.instance_id] = m.component.mass_kg
            fs, assumptions, summary = urdf_check(urdf, a.instances, a.feats, a.part_names, dens, known, urdf_map,
                                                  [Path(urdf).parent, Path(step).parent])
            report.findings += fs
            report.assumptions += assumptions
            report.stats["urdf"] = summary
            rec["measurements"] = {"links": len(summary.get("links", {}))}

    if prev_step:
        changes = []
        with st.stage("revision_comparison") as rec:
            from .diff import diff, label_findings
            old = analyse(prev_step, library, cache, limits, Stages(), workdir)
            old_findings = list(old.findings)
            if prev_bom:
                old_findings += reconcile(read_bom(prev_bom), old.parts, old.instances).findings
            changes = diff(old, a)
            old.release()
            del old
            report.changes = [c.to_dict() for c in changes]
            report.fixed = label_findings(old_findings, report.findings)
            rec["measurements"] = {"changed_parts": len(changes), "fixed_findings": len(report.fixed)}
        if drawings:
            with st.stage("drawing_consistency") as rec:
                from .diff import drawing_findings, read_drawings
                cands = {p.name: p.name for p in a.parts.values()}
                revs = {}
                if bom_result:
                    for i, pid in bom_result.pairs.items():
                        r = rows[i]
                        if r.part_number:
                            cands[r.part_number] = a.parts[pid].name
                        if r.revision:
                            revs[a.parts[pid].name] = r.revision
                dws = read_drawings([Path(d) for d in drawings], cands, llm)
                report.findings += drawing_findings(dws, changes, revs)
                report.stats["drawings"] = dws
                rec["measurements"] = {"drawings": len(dws), "matched": sum(1 for d in dws if d["part"])}
    elif drawings:
        st.skip("drawing_consistency", "drawings need a previous revision to judge staleness")
    st.skip("gdt_dimensions", "GD&T and tolerance reading are not in this engine version")
    st.skip("manufacturing", "manufacturing checks are not in this engine version")

    if glb:
        from .report import write_glb
        try:
            write_glb(a.instances, glb)
        except Exception as e:  # noqa: BLE001 - no 3D view is a missing picture, not a failed check
            notes.append(f"3D view not available: {e}")

    report.assumptions += notes
    matched = a.checker.matches if a.checker else {}
    report.parts = [{"part": p.name, "count": sum(1 for i in a.instances if i.part_id == pid),
                     "volume_mm3": round(p.signature.get("volume", 0), 2), "bbox_mm": p.signature.get("bbox"),
                     "holes": len(a.part_feats[pid].holes), "valid": p.valid,
                     "geometry_type": a.part_feats[pid].geometry_type, "faces": a.part_feats[pid].face_count,
                     "geometry_hash": a.part_hashes.get(pid, ""), "cached": a.part_feats[pid].cached,
                     "component": next((m.component.name for iid, m in matched.items()
                                        if a.part_names[iid] == p.name), None)}
                    for pid, p in a.parts.items()]
    report.instances = [{"id": i.instance_id, "path": i.path, "part": a.part_names[i.instance_id],
                         "transform": i.transform.round(6).tolist()} for i in a.instances]
    report.interfaces = [{"a": c.a.path, "b": c.b.path, "planes": len(c.planes()), "exact": c.exact,
                          "distance_mm": None if c.distance is None else round(c.distance, 4)} for c in a.contacts]

    report.stats.update({"parts": len(a.parts), "instances": len(a.instances)})
    with st.stage("evidence") as rec:
        from .llm import narrate
        report.narrative = narrate(llm, report.to_dict())
        rec["measurements"] = {"narrative": report.narrative.get("status")}
    a.release()
    with st.stage("final_report") as rec:
        rec["measurements"] = {"findings": len(report.findings)}
    report.stages = st.finalize(report.findings)
    report.stats.update({
        "parts": len(a.parts), "instances": len(a.instances), "interfaces": len(report.interfaces),
        "timings": a.timings, "runtime_s": round(time.time() - t_start, 3), "peak_rss_mb": round(st.peak_mb, 1),
        "complexity": {k: v for k, v in complexity.to_dict().items() if k != "counts"},
        "cache": _cache_stats(cache.hits - hits0, cache.misses - misses0),
        "limits": limits.plan, "engine_version": ENGINE_VERSION})
    report.llm_usage = llm.usage.to_dict() if not isinstance(llm, NoLLM) else {"calls": 0, "configured": False}
    return report
