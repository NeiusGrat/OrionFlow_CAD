"""SQLite corpus store — the scale-run backend (W5).

One row per record, with the full JSON payload kept intact alongside the
columns the audit queries. Five thousand loose JSON files is a directory the
filesystem hates and no query can touch; the same data in SQLite answers
"how many distinct signatures carry a Draft" in milliseconds.

Schema note: ``blueprint_hash`` is NOT unique — a stress variant and its
clean parent legitimately differ, but two clean draws with identical frozen
blueprints are true duplicates. ``(blueprint_hash, status)`` is the primary
key so a re-run overwrites rather than silently duplicating, and the
duplicate rate is measurable instead of assumed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    blueprint_hash   TEXT NOT NULL,
    status           TEXT NOT NULL,   -- clean | natural | stress | injected
    tag              TEXT,
    family           TEXT,
    base_family      TEXT,
    attachments      TEXT,            -- json list
    n_attachments    INTEGER,
    datum_strategy   TEXT,            -- json dict
    signature        TEXT,            -- feature_sequence_hash
    feature_seq      TEXT,            -- json list
    tier_max         INTEGER,
    passed           INTEGER,
    predicted_volume REAL,
    measured_volume  REAL,
    rel_err          REAL,
    n_assertions     INTEGER,
    fault            TEXT,
    repair_source    TEXT,
    elapsed_s        REAL,
    -- corpus_v2 metadata (Phase-X Step 2): every audit dimension a column, so
    -- future audits query rather than reopen and reparse every payload.
    topology_signature  TEXT,
    verification_tier   INTEGER,   -- effective body/verification tier 1/2/3
    failure_mechanism   TEXT,      -- repair records only
    repair_origin       TEXT,      -- injected | stress | natural | real ...
    entropy_bucket      TEXT,      -- volume-decade bucket for spread tracking
    generator_version   TEXT,
    audit_version       TEXT,
    verification_method TEXT,      -- closed_form | mesh_converged | ...
    payload          TEXT NOT NULL,   -- the full record JSON
    PRIMARY KEY (blueprint_hash, status)
);
CREATE INDEX IF NOT EXISTS idx_family    ON records(family);
CREATE INDEX IF NOT EXISTS idx_base      ON records(base_family);
CREATE INDEX IF NOT EXISTS idx_status    ON records(status);
CREATE INDEX IF NOT EXISTS idx_signature ON records(signature);
CREATE INDEX IF NOT EXISTS idx_passed    ON records(passed);
"""
# idx_vtier / idx_mechanism are created in _ensure_columns, AFTER the v2
# columns are guaranteed to exist (a pre-v2 table lacks them at CREATE time).

GENERATOR_VERSION = "orion-forge-2.0"   # parallel batched forge era
AUDIT_VERSION = "2"                       # corpus_v2 metadata schema

#: New metadata columns added by the v2 migration (older DBs lack them).
_V2_COLUMNS = [
    ("topology_signature", "TEXT"), ("verification_tier", "INTEGER"),
    ("failure_mechanism", "TEXT"), ("repair_origin", "TEXT"),
    ("entropy_bucket", "TEXT"), ("generator_version", "TEXT"),
    ("audit_version", "TEXT"), ("verification_method", "TEXT"),
]


def _ensure_columns(con: sqlite3.Connection) -> None:
    """Add any missing v2 metadata columns to an existing table (idempotent).
    ALTER TABLE ADD COLUMN is cheap and lets an old corpus open forward-
    compatibly; values stay NULL until the backfill migration runs."""
    have = {r[1] for r in con.execute("PRAGMA table_info(records)").fetchall()}
    for name, typ in _V2_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE records ADD COLUMN {name} {typ}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_vtier ON records(verification_tier)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_mechanism "
                "ON records(failure_mechanism)")


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    _ensure_columns(con)
    # Bulk-insert friendly: the corpus is regenerable, so durability per
    # row is not worth the fsync cost.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _body_numbers(verdict: dict) -> tuple[Optional[float], Optional[float],
                                          Optional[float]]:
    for a in verdict.get("assertions", []):
        if a.get("id") == "body":
            return (a.get("target"), a.get("measured"), a.get("rel_err"))
    return (None, None, None)


def _entropy_bucket(pred, meas) -> Optional[str]:
    """Coarse volume-decade bucket, for cheap distributional-spread tracking
    across the corpus without reparsing payloads."""
    v = meas if meas else pred
    if not v or v <= 0:
        return None
    import math
    return f"1e{int(math.floor(math.log10(v)))}"


def _derive_metadata(payload: dict, status: str) -> dict:
    """The corpus_v2 audit dimensions, computed once at write time.

    verification_tier — the EFFECTIVE tier of the record's mass property:
      real CAD from its verification.status; clean synthetic from the
      body_tier overlay or the body assertion; repair records have none.
    verification_method — how that tier was established.
    failure_mechanism / repair_origin — for repair records only.
    """
    bp = payload.get("blueprint", {})
    verdict = payload.get("verdict", {})
    trace = payload.get("repair_trace", {}) or {}
    ver = payload.get("verification", {}) or {}

    vtier = None
    vmethod = None
    if status in ("real", "real_variant"):
        vstatus = ver.get("status")
        vtier = 1 if vstatus == "tier1_exact" else (3 if vstatus else None)
        vmethod = ver.get("method") or "import"
    elif status == "clean":
        bt = payload.get("body_tier")
        if bt is not None:
            vtier = bt
        for a in bp.get("assertions", []):
            if a.get("id") in ("body", "shelled") or a.get("kind") in (
                    "body_volume", "volume_between", "body_mesh_converged"):
                kind = a.get("kind")
                if vtier is None:
                    vtier = (3 if kind == "volume_between"
                             else 2 if kind == "body_mesh_converged"
                             else a.get("tier"))
                vmethod = ("mesh_converged" if kind == "body_mesh_converged"
                           else "bounded" if kind == "volume_between"
                           else "closed_form")
                break

    mechanism = None
    if status in ("injected", "stress", "natural"):
        mechanism = trace.get("mechanism")
        if not mechanism:
            log = verdict.get("build_log", {}) or {}
            if log.get("timeout"):
                mechanism = "kernel_timeout"
            elif verdict.get("refused"):
                mechanism = "precondition_refused"
            elif (log.get("build_report", {}) or {}).get("recompute_errors"):
                mechanism = "occ_build_error"
            elif not verdict.get("build_ok"):
                mechanism = "no_solid"
            else:
                mechanism = "verification_mismatch"

    pred, meas, _err = _body_numbers(verdict)
    return {
        "verification_tier": vtier,
        "verification_method": vmethod,
        "failure_mechanism": mechanism,
        "repair_origin": trace.get("source") or (
            status if status in ("injected", "stress", "natural") else None),
        "entropy_bucket": _entropy_bucket(pred, meas),
        "generator_version": bp.get("generator_version", GENERATOR_VERSION),
        "audit_version": AUDIT_VERSION,
    }


_COLUMNS = [
    "blueprint_hash", "status", "tag", "family", "base_family", "attachments",
    "n_attachments", "datum_strategy", "signature", "feature_seq", "tier_max",
    "passed", "predicted_volume", "measured_volume", "rel_err", "n_assertions",
    "fault", "repair_source", "elapsed_s", "topology_signature",
    "verification_tier", "failure_mechanism", "repair_origin", "entropy_bucket",
    "generator_version", "audit_version", "verification_method", "payload",
]


def insert(con: sqlite3.Connection, payload: dict, status: str) -> None:
    bp = payload.get("blueprint", {})
    verdict = payload.get("verdict", {})
    trace = payload.get("repair_trace", {}) or {}
    pred, meas, err = _body_numbers(verdict)
    atts = payload.get("attachments", []) or []
    tiers = [a.get("tier") for a in bp.get("assertions", [])
             if isinstance(a.get("tier"), int)]
    md = _derive_metadata(payload, status)
    sig = payload.get("feature_sequence_hash")
    values = (
        bp.get("blueprint_hash", ""), status, verdict.get("tag"),
        payload.get("recipe"), payload.get("base_family"),
        json.dumps(atts), len(atts),
        json.dumps(payload.get("datum_strategy", {})), sig,
        json.dumps(payload.get("feature_seq", [])),
        max(tiers) if tiers else None,
        1 if verdict.get("passed") else 0, pred, meas, err,
        len(verdict.get("assertions", [])),
        trace.get("fault"), trace.get("source"), verdict.get("elapsed_s"),
        sig, md["verification_tier"], md["failure_mechanism"],
        md["repair_origin"], md["entropy_bucket"], md["generator_version"],
        md["audit_version"], md["verification_method"],
        json.dumps(payload),
    )
    placeholders = ",".join("?" * len(_COLUMNS))
    con.execute(
        f"INSERT OR REPLACE INTO records ({','.join(_COLUMNS)}) "
        f"VALUES ({placeholders})", values)


def audit(con: sqlite3.Connection) -> dict[str, Any]:
    """Everything the training-readiness report needs, in one pass."""
    q = con.execute
    out: dict[str, Any] = {}
    out["records"] = q("SELECT COUNT(*) FROM records").fetchone()[0]
    out["by_status"] = dict(q(
        "SELECT status, COUNT(*) FROM records GROUP BY status").fetchall())
    out["distinct_signatures"] = q(
        "SELECT COUNT(DISTINCT signature) FROM records").fetchone()[0]
    out["distinct_families"] = q(
        "SELECT COUNT(DISTINCT family) FROM records").fetchone()[0]
    out["distinct_bases"] = q(
        "SELECT COUNT(DISTINCT base_family) FROM records").fetchone()[0]
    out["family_distribution"] = dict(q(
        "SELECT family, COUNT(*) FROM records GROUP BY family "
        "ORDER BY 2 DESC").fetchall())
    out["attachment_distribution"] = dict(q(
        "SELECT n_attachments, COUNT(*) FROM records "
        "GROUP BY n_attachments ORDER BY 1").fetchall())
    out["datum_distribution"] = dict(q(
        "SELECT datum_strategy, COUNT(*) FROM records "
        "GROUP BY datum_strategy").fetchall())
    out["tier_distribution"] = dict(q(
        "SELECT tier_max, COUNT(*) FROM records GROUP BY tier_max").fetchall())
    out["fault_distribution"] = dict(q(
        "SELECT fault, COUNT(*) FROM records WHERE fault IS NOT NULL "
        "GROUP BY fault ORDER BY 2 DESC").fetchall())
    # duplicate rate: identical blueprint hash appearing under >1 tag
    out["duplicate_blueprints"] = q(
        "SELECT COUNT(*) FROM (SELECT blueprint_hash FROM records "
        "GROUP BY blueprint_hash HAVING COUNT(*) > 1)").fetchone()[0]
    row = q("SELECT AVG(rel_err), MAX(rel_err) FROM records "
            "WHERE passed=1 AND rel_err IS NOT NULL").fetchone()
    out["clean_rel_err_mean"] = row[0]
    out["clean_rel_err_max"] = row[1]
    return out


def signature_counts(con: sqlite3.Connection) -> list[tuple]:
    return con.execute(
        "SELECT signature, COUNT(*) FROM records GROUP BY signature "
        "ORDER BY 2 DESC").fetchall()


def feature_coverage(con: sqlite3.Connection) -> dict[str, int]:
    """How many records exercise each feature type, from the stored
    sequences — the corpus-level answer to 'is every operation taught?'"""
    counts: dict[str, int] = {}
    for (seq_json,) in con.execute("SELECT feature_seq FROM records"):
        for f in set(json.loads(seq_json or "[]")):
            counts[f] = counts.get(f, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def failure_analysis(con) -> dict:
    """Why records failed, separated by MECHANISM rather than lumped as
    'failed': a kernel timeout, a build that never produced a solid, and a
    build that produced the wrong solid are three different engineering
    problems and only the third is a verification finding."""
    import json as _json
    out = {"timeout": 0, "build_failed": 0, "verification_failed": 0,
           "refused_precondition": 0, "passed": 0, "real_cad": 0}
    modes: dict = {}
    for status, payload in con.execute(
            "SELECT status, payload FROM records"):
        # Imported real CAD builds fine; measured_only means "not closed-form
        # provable" (B-splines), NOT "failed". Counting it as a build failure
        # would invent hundreds of phantom failures.
        if status in ("real", "real_variant"):
            out["real_cad"] += 1
            continue
        p = _json.loads(payload)
        v = p.get("verdict", {})
        log = v.get("build_log", {}) or {}
        if v.get("passed"):
            out["passed"] += 1
            continue
        if log.get("timeout"):
            out["timeout"] += 1
            key = "kernel_timeout"
        elif v.get("refused"):
            out["refused_precondition"] += 1
            key = "precondition:" + (
                (v.get("failed_preconditions") or [{}])[0].get("id", "?"))
        elif not v.get("build_ok"):
            out["build_failed"] += 1
            errs = (log.get("build_report", {}) or {}).get(
                "recompute_errors", [])
            key = "build:" + (errs[0].get("error", "unknown")[:40]
                              if errs else "no_solid")
        else:
            out["verification_failed"] += 1
            bad = [a.get("id") for a in v.get("assertions", [])
                   if not a.get("passed")]
            key = "assert:" + (bad[0] if bad else "?")
        modes[key] = modes.get(key, 0) + 1
    out["top_modes"] = sorted(modes.items(), key=lambda kv: -kv[1])[:10]
    return out


def verification_analysis(con) -> dict:
    """Tier mix for REAL records (imported CAD), which carry a per-record
    verification status rather than a frozen contract."""
    import json as _json
    out: dict = {}
    for (payload,) in con.execute(
            "SELECT payload FROM records WHERE status LIKE 'real%'"):
        st = (_json.loads(payload).get("verification") or {}).get(
            "status", "unverified")
        out[st] = out.get(st, 0) + 1
    return out


def diversity_and_confidence(con) -> dict:
    """The analyses that decide resource allocation, all keyed on topology
    rather than on yield.

    * ``per_family`` — failures distributed ACROSS families, not just summed.
      A 20% aggregate failure rate means something very different when it is
      one family failing 90% of the time than when it is spread evenly.
    * ``root_cause`` — verification failures grouped by the KIND of assertion
      that broke (volume / extent / connectivity / precondition), which is
      what says whether the gap is geometric prediction or the model of the
      part itself.
    * ``by_origin`` — whether a failure came from a deliberately injected or
      stressed record (expected, and good) or from a naturally generated one
      (a real gap in the generator or the verifier).
    * ``low_confidence_topologies`` — signatures that EXIST but whose records
      are mostly tier 2/3 or unverified. These are the coverage gaps: the
      corpus knows the shape but cannot prove it, so they are worth more
      verification investment than new shapes are.
    """
    import json as _json
    per_family: dict = {}
    root_cause: dict = {}
    by_origin: dict = {}
    sig_tier: dict = {}

    for fam, status, sig, tier, passed, payload in con.execute(
            "SELECT family, status, signature, tier_max, passed, payload "
            "FROM records"):
        is_real = status in ("real", "real_variant")
        f = per_family.setdefault(
            fam or "?", {"records": 0, "passed": 0, "failed": 0,
                         "signatures": set()})
        f["records"] += 1
        f["signatures"].add(sig)
        # Confidence scoring is for GENERATED topologies: a real part is a
        # single sample, not a shape the generator can or cannot prove.
        if not is_real:
            st = sig_tier.setdefault(
                sig, {"n": 0, "t1": 0, "t23": 0, "unver": 0, "family": fam})
            st["n"] += 1
            if tier == 1:
                st["t1"] += 1
            elif tier in (2, 3):
                st["t23"] += 1
            else:
                st["unver"] += 1

        if passed:
            f["passed"] += 1
            continue
        if is_real:
            continue          # measured_only real CAD is not a failure
        f["failed"] += 1

        origin = ("injected/stress" if status in ("injected", "stress")
                  else "natural")
        by_origin[origin] = by_origin.get(origin, 0) + 1

        v = _json.loads(payload).get("verdict", {})
        if v.get("refused"):
            root_cause["precondition_refusal"] =                 root_cause.get("precondition_refusal", 0) + 1
            continue
        kinds = {a.get("kind") for a in v.get("assertions", [])
                 if not a.get("passed")}
        if not kinds:
            root_cause["no_build"] = root_cause.get("no_build", 0) + 1
        for k in kinds:
            label = {"body_volume": "volume_mismatch",
                     "feature_volume": "feature_volume_mismatch",
                     "bbox_extent": "extent_mismatch",
                     "solids": "connectivity",
                     "watertight": "connectivity",
                     "volume_between": "bounded_volume_out_of_band",
                     "precondition": "precondition"}.get(k, k or "unknown")
            root_cause[label] = root_cause.get(label, 0) + 1

    for f in per_family.values():
        f["signatures"] = len(f["signatures"])
        f["fail_rate"] = round(f["failed"] / max(f["records"], 1), 3)

    low_conf = sorted(
        ({"signature": sig, "family": st["family"], "records": st["n"],
          "tier1_share": round(st["t1"] / st["n"], 2)}
         for sig, st in sig_tier.items() if st["n"] >= 2
         and st["t1"] / st["n"] < 0.5),
        key=lambda r: (r["tier1_share"], -r["records"]))

    return {"per_family": per_family, "root_cause": root_cause,
            "by_origin": by_origin,
            "low_confidence_topologies": low_conf[:20],
            "n_low_confidence": len(low_conf),
            "n_signatures_scored": len(sig_tier)}


def confidence_tiers(con) -> dict:
    """Whole-corpus breakdown by verification confidence. Distinguishes
    independently-verified geometry from repair records (deliberately broken /
    naturally failed), which are valuable training data but are NOT verified
    parts. Answers: how much of the corpus is now independently verified?"""
    import json as _json
    out = {"tier1_exact_verified": 0, "tier2_numerical": 0,
           "tier3_bounded": 0, "repair_record": 0, "unverified": 0}
    for status, tier_max, passed, payload in con.execute(
            "SELECT status, tier_max, passed, payload FROM records"):
        if status in ("injected", "stress", "natural"):
            out["repair_record"] += 1
            continue
        if status in ("real", "real_variant"):
            v = (_json.loads(payload).get("verification") or {}).get("status")
            if v == "tier1_exact":
                out["tier1_exact_verified"] += 1
            elif v == "measured_only":
                out["unverified"] += 1
            else:
                out["unverified"] += 1
            continue
        # clean synthetic — prefer an explicit body_tier overlay (Milestone-A
        # re-tier) over the frozen assertion tier when present.
        bt = _json.loads(payload).get("body_tier")
        eff = bt if bt is not None else tier_max
        if passed and eff == 1:
            out["tier1_exact_verified"] += 1
        elif passed and eff == 2:
            out["tier2_numerical"] += 1
        elif passed and eff == 3:
            out["tier3_bounded"] += 1
        else:
            out["unverified"] += 1
    return out


def family_body_tier(con) -> dict:
    """Per family: how its records' BODY verification is tiered. Body tier is
    the closure metric — a family is 'covered' at Tier 1 when its whole-solid
    volume has an exact closed-form proof, independent of precondition or
    integrity-check tags. Uses the body_tier overlay when present, else the
    body/volume_between/body_mesh_converged assertion tier."""
    import json as _json
    out: dict = {}
    for family, status, payload in con.execute(
            "SELECT family, status, payload FROM records WHERE status='clean'"):
        p = _json.loads(payload)
        bt = p.get("body_tier")
        if bt is None:
            for a in p.get("blueprint", {}).get("assertions", []):
                if a.get("id") in ("body", "shelled") or                         a.get("kind") in ("body_volume", "volume_between",
                                          "body_mesh_converged"):
                    if a.get("kind") == "volume_between":
                        bt = 3
                    elif a.get("kind") == "body_mesh_converged":
                        bt = 2
                    else:
                        bt = a.get("tier")
                    break
        d = out.setdefault(family or "?", {1: 0, 2: 0, 3: 0, "none": 0})
        d[bt if bt in (1, 2, 3) else "none"] += 1
    return out
