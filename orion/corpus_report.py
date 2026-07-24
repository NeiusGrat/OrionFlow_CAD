"""W8 training-readiness audit — is the corpus diverse, or just expanded?

Reads the SQLite corpus and writes ``corpus_report_v1.md``. The report is
deliberately adversarial about its own dataset: alongside the distributions
it computes the numbers that expose parameter-expansion masquerading as
diversity —

  * signature entropy vs family entropy (a corpus of 40 names that collapses
    to 6 signatures is 6 topologies with 40 labels);
  * the effective family count 2**H, which says how many families the corpus
    behaves like regardless of how many exist;
  * top-signature share (if one signature is 30% of the corpus, that is the
    corpus);
  * duplicate blueprint hashes (identical frozen contracts);
  * per-feature record counts, so an "≥10 examples" claim is checkable.

Usage:
    python -m orion.corpus_report --db data/forge/corpus_v2.db
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any

from . import corpus_db

TARGET_FEATURES = ("Thickness", "Draft", "Fillet", "Chamfer", "LinearPattern",
                   "PolarPattern", "Mirrored", "Sweep", "Loft", "Groove",
                   "Revolution", "Pad", "Pocket")


def _entropy(counts) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts if c > 0)


def _bar(n: int, total: int, width: int = 34) -> str:
    filled = int(round(width * n / total)) if total else 0
    return "#" * filled + "." * (width - filled)


def build_report(db_path: str, out_path: str) -> dict[str, Any]:
    con = corpus_db.connect(db_path)
    a = corpus_db.audit(con)
    sigs = corpus_db.signature_counts(con)
    feat = corpus_db.feature_coverage(con)

    sig_counts = [c for _s, c in sigs]
    fam_counts = list(a["family_distribution"].values())
    sig_H = _entropy(sig_counts)
    fam_H = _entropy(fam_counts)
    total = a["records"] or 1
    top_share = (sig_counts[0] / total) if sig_counts else 0.0

    clean = a["by_status"].get("clean", 0)
    injected = a["by_status"].get("injected", 0)
    natural = a["by_status"].get("natural", 0) + a["by_status"].get("stress", 0)
    nat_rate = natural / total

    verdict = {
        "records>=5000": total >= 5000,
        "signature_entropy>4.5": sig_H > 4.5,
        "natural_failures_15_25pct": 0.15 <= nat_rate <= 0.25,
        "distinct_signatures>=60": a["distinct_signatures"] >= 60,
        "feature_coverage>=10": all(feat.get(f, 0) >= 10
                                    for f in TARGET_FEATURES),
        "no_duplicate_blueprints": a["duplicate_blueprints"] == 0,
        "clean_exactness<1e-6": (a["clean_rel_err_max"] or 0) < 1e-6,
    }

    L = []
    L.append("# OrionForge corpus report v1\n")
    L.append(f"Source: `{db_path}`\n")
    L.append("## Verdict\n")
    L.append("| Gate | Target | Result |")
    L.append("|---|---|---|")
    L.append(f"| Records | >=5000 | {total} |")
    L.append(f"| Signature entropy | >4.5 bits | {sig_H:.2f} |")
    L.append(f"| Distinct signatures | >=60 | {a['distinct_signatures']} |")
    L.append(f"| Natural failure rate | 15-25% | {nat_rate:.1%} |")
    L.append(f"| Feature coverage | >=10 each | "
             f"{'yes' if verdict['feature_coverage>=10'] else 'NO'} |")
    L.append(f"| Duplicate blueprints | 0 | {a['duplicate_blueprints']} |")
    L.append(f"| Clean max rel err | <1e-6 | "
             f"{a['clean_rel_err_max']:.2e} |"
             if a["clean_rel_err_max"] is not None else
             "| Clean max rel err | <1e-6 | n/a |")
    L.append("")
    L.append(f"**{sum(verdict.values())}/{len(verdict)} gates passed.**\n")

    L.append("## Topology diversity — is this diversity or parameter "
             "expansion?\n")
    eff_sig = 2 ** sig_H
    L.append("| Measure | Value |")
    L.append("|---|---|")
    L.append(f"| Effective topologies 2^H | **{eff_sig:.0f}** |")
    L.append(f"| Raw distinct signatures | {a['distinct_signatures']} |")
    L.append(f"| Effective / raw | **{eff_sig / max(a['distinct_signatures'], 1):.2f}** |")
    L.append(f"| Signature entropy | {sig_H:.2f} bits |")
    L.append(f"| Family entropy | {fam_H:.2f} bits "
             f"({2 ** fam_H:.0f} effective families) |")
    L.append(f"| Named families | {a['distinct_families']} |")
    L.append(f"| Family-to-topology ratio | **{a['distinct_families'] / max(a['distinct_signatures'], 1):.3f}** |")
    L.append(f"| Unique-signature rate | {a['distinct_signatures'] / total:.1%} |")
    L.append(f"| Top-signature concentration | {top_share:.1%} |")
    L.append(f"| Duplicate blueprints | {a['duplicate_blueprints']} |")
    L.append("")
    ratio = eff_sig / max(a["distinct_signatures"], 1)
    if ratio < 0.5:
        L.append("**Reading:** effective topologies sit well below the raw "
                 "signature count — the distribution has a long thin tail "
                 "and a few shapes carry the corpus. More recipes would add "
                 "names, not information.")
    else:
        L.append("**Reading:** effective topologies track the raw signature "
                 "count, so the distribution is broad rather than "
                 "concentrated: signatures are being genuinely exercised, "
                 "not merely present.")
    fam_ratio = a["distinct_families"] / max(a["distinct_signatures"], 1)
    if fam_ratio > 0.8:
        L.append("Family-to-topology ratio near 1.0 means each family "
                 "contributes roughly one shape — composition is NOT "
                 "multiplying topologies and is the thing to invest in.")
    else:
        L.append(f"Family-to-topology ratio {fam_ratio:.2f} means each named "
                 f"family yields about {1 / max(fam_ratio, 1e-9):.1f} "
                 f"distinct topologies — composition is multiplying "
                 f"diversity rather than relabelling it.")
    L.append("")

    L.append("## Record mix\n")
    L.append("| Status | Count | Share |")
    L.append("|---|---|---|")
    for st, c in sorted(a["by_status"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {st} | {c} | {c / total:.1%} |")
    L.append(f"\nclean:natural:injected = {clean}:{natural}:{injected}\n")

    L.append("## Family distribution\n```")
    for fam, c in list(a["family_distribution"].items())[:40]:
        L.append(f"{fam:<24} {c:>5}  {_bar(c, total)}")
    L.append("```\n")

    L.append("## Feature coverage (records exercising each op)\n```")
    for f, c in feat.items():
        flag = "" if c >= 10 else "   <-- under 10"
        L.append(f"{f:<18} {c:>5}{flag}")
    L.append("```\n")

    L.append("## Attachment count distribution\n```")
    for k, c in sorted(a["attachment_distribution"].items(),
                       key=lambda kv: (kv[0] is None, kv[0])):
        L.append(f"{str(k):<4} attachments  {c:>5}  {_bar(c, total)}")
    L.append("```\n")

    L.append(f"## Datum strategies\n\n{len(a['datum_distribution'])} distinct "
             f"strategies in use.\n")

    L.append("## Tier distribution (max tier per record)\n```")
    for t, c in sorted(a["tier_distribution"].items(),
                       key=lambda kv: (kv[0] is None, kv[0])):
        L.append(f"tier {t}: {c:>5}  {_bar(c, total)}")
    L.append("```\n")

    if a["fault_distribution"]:
        L.append("## Fault distribution\n```")
        for f, c in a["fault_distribution"].items():
            L.append(f"{f:<34} {c:>5}")
        L.append("```\n")

    L.append("## Top 25 signatures\n```")
    for sig, c in sigs[:25]:
        L.append(f"{sig}  {c:>4}  {_bar(c, total)}")
    L.append("```\n")

    fa = corpus_db.failure_analysis(con)
    L.append("## Failure analysis\n")
    L.append("| Mechanism | Count | Share |")
    L.append("|---|---|---|")
    for k in ("passed", "verification_failed", "refused_precondition",
              "build_failed", "timeout"):
        L.append(f"| {k} | {fa[k]} | {fa[k] / total:.1%} |")
    L.append("\n### Top 10 failure modes\n```")
    for mode, c in fa["top_modes"]:
        L.append(f"{mode:<46} {c:>5}")
    L.append("```\n")

    va = corpus_db.verification_analysis(con)
    if va:
        vt = sum(va.values())
        L.append("## Verification analysis (imported real CAD)\n")
        L.append("| Status | Count | Share |")
        L.append("|---|---|---|")
        for k, c in sorted(va.items(), key=lambda kv: -kv[1]):
            L.append(f"| {k} | {c} | {c / vt:.1%} |")
        L.append("")

    dc = corpus_db.diversity_and_confidence(con)

    L.append("## Verification failures by ROOT CAUSE\n")
    L.append("| Root cause | Count |")
    L.append("|---|---|")
    for k, c in sorted(dc["root_cause"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {c} |")
    L.append("")

    L.append("## Failure origin: expected vs real gap\n")
    L.append("| Origin | Failures |")
    L.append("|---|---|")
    for k, c in sorted(dc["by_origin"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {c} |")
    inj = dc["by_origin"].get("injected/stress", 0)
    nat = dc["by_origin"].get("natural", 0)
    L.append(f"\nInjected/stress failures are EXPECTED (the fault was put "
             f"there deliberately). Natural failures are the real signal: "
             f"**{nat}** of {inj + nat} failures "
             f"({nat / max(inj + nat, 1):.1%}) came from records nobody "
             f"broke on purpose.\n")

    L.append("## Failures distributed across families\n")
    L.append("| Family | Records | Signatures | Failed | Fail rate |")
    L.append("|---|---|---|---|---|")
    for fam, d in sorted(dc["per_family"].items(),
                         key=lambda kv: -kv[1]["fail_rate"])[:25]:
        L.append(f"| {fam} | {d['records']} | {d['signatures']} | "
                 f"{d['failed']} | {d['fail_rate']:.0%} |")
    L.append("")

    L.append("## Coverage gaps: topology exists, verification confidence low\n")
    L.append(f"{dc['n_low_confidence']} of {dc['n_signatures_scored']} "
             f"signatures have under half their records at tier 1. These are "
             f"shapes the corpus can BUILD but cannot PROVE — the highest-"
             f"value target for verification investment.\n")
    if dc["low_confidence_topologies"]:
        L.append("| Signature | Family | Records | Tier-1 share |")
        L.append("|---|---|---|---|")
        for r in dc["low_confidence_topologies"]:
            L.append(f"| {r['signature']} | {r['family']} | {r['records']} | "
                     f"{r['tier1_share']:.0%} |")
        L.append("")

    ct = corpus_db.confidence_tiers(con)
    ct_tot = sum(ct.values()) or 1
    verified = ct["tier1_exact_verified"] + ct["tier2_numerical"] + ct["tier3_bounded"]
    L.append("## Confidence tier distribution (whole corpus)\n")
    L.append("| Confidence | Count | Share |")
    L.append("|---|---|---|")
    for k in ("tier1_exact_verified", "tier2_numerical", "tier3_bounded",
              "repair_record", "unverified"):
        L.append(f"| {k} | {ct[k]} | {ct[k] / ct_tot:.1%} |")
    L.append(f"\n**Independently verified geometry: {verified} / {ct_tot} "
             f"({verified / ct_tot:.1%})**; unverified: {ct['unverified']}. "
             f"Repair records ({ct['repair_record']}) are deliberately-broken "
             f"or naturally-failed examples — training signal, not verified "
             f"parts.\n")

    con.close()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    return {"out": out_path, "records": total,
            "root_cause": dc["root_cause"],
            "failures_by_origin": dc["by_origin"],
            "low_confidence_topologies": dc["n_low_confidence"],
            "signatures_scored": dc["n_signatures_scored"],
            "failure_analysis": {k: v for k, v in fa.items()
                                 if k != "top_modes"},
            "top_failure_modes": fa["top_modes"][:10],
            "verification_analysis": va,
            "family_to_topology_ratio": round(
                a["distinct_families"] / max(a["distinct_signatures"], 1), 3),
            "signature_entropy": round(sig_H, 3),
            "effective_topologies": round(eff_sig, 1),
            "distinct_signatures": a["distinct_signatures"],
            "natural_failure_rate": round(nat_rate, 3),
            "top_signature_share": round(top_share, 4),
            "duplicate_blueprints": a["duplicate_blueprints"],
            "confidence_tiers": ct,
            "independently_verified": verified,
            "gates": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    ap.add_argument("--out", default="data/forge/corpus_report_v1.md")
    args = ap.parse_args()
    print(json.dumps(build_report(args.db, args.out), indent=1))


if __name__ == "__main__":
    main()
