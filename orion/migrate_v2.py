"""Backfill corpus_v2 metadata columns on an existing corpus (Phase-X Step 2).

connect() already adds the columns forward-compatibly; this repopulates them
for every existing record by re-inserting through corpus_db.insert (idempotent
on the (blueprint_hash, status) key). Payloads are untouched — only the
denormalised metadata columns are (re)computed. Never regenerates geometry.

Usage:
    python -m orion.migrate_v2 --db data/forge/corpus_v2.db
"""

from __future__ import annotations

import argparse
import json

from . import corpus_db


def run(db_path: str) -> dict:
    con = corpus_db.connect(db_path)          # adds columns if missing
    rows = con.execute("SELECT status, payload FROM records").fetchall()
    for i, (status, payload) in enumerate(rows, 1):
        corpus_db.insert(con, json.loads(payload), status)
        if i % 500 == 0:
            con.commit()
    con.commit()

    # verification: every non-repair record should now have a verification_tier
    # populated (or be a real measured_only), and every repair a mechanism.
    missing_tier = con.execute(
        "SELECT COUNT(*) FROM records WHERE status IN "
        "('clean','real','real_variant') AND verification_tier IS NULL"
    ).fetchone()[0]
    missing_mech = con.execute(
        "SELECT COUNT(*) FROM records WHERE status IN "
        "('injected','stress','natural') AND failure_mechanism IS NULL"
    ).fetchone()[0]
    dist_tier = dict(con.execute(
        "SELECT verification_tier, COUNT(*) FROM records "
        "GROUP BY verification_tier").fetchall())
    dist_mech = dict(con.execute(
        "SELECT failure_mechanism, COUNT(*) FROM records "
        "WHERE failure_mechanism IS NOT NULL GROUP BY failure_mechanism"
    ).fetchall())
    genv = dict(con.execute(
        "SELECT generator_version, COUNT(*) FROM records "
        "GROUP BY generator_version").fetchall())
    con.close()
    return {"migrated": len(rows),
            "records_missing_verification_tier": missing_tier,
            "repairs_missing_mechanism": missing_mech,
            "verification_tier_distribution": {str(k): v
                                               for k, v in dist_tier.items()},
            "failure_mechanism_distribution": dist_mech,
            "generator_version_distribution": genv}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    args = ap.parse_args()
    print(json.dumps(run(args.db), indent=1))


if __name__ == "__main__":
    main()
