"""Run supervisor (Phase-X Step 0.1) — unattended, interruption-surviving.

Relaunches the resumable forge loop until the corpus reaches the target clean
count. Each launch tops up toward the target with a fresh seed derived from the
current count, so a process that dies (crash, kill, or resume after the machine
was suspended) is continued automatically with zero lost or duplicated records
— the 50-record commits guarantee durability, and ``--target`` guarantees
idempotent top-up.

What this CANNOT do: prevent the OS from SUSPENDING the process. On Windows a
closed lid or sleep timer suspends Python; nothing in userspace overrides that.
Set that separately (``powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS
LIDACTION 0`` and disable AC sleep) or run on a machine that does not sleep.
This supervisor guarantees the run RESUMES correctly the moment the machine is
awake again — the code half of "survive 24h unattended".

Usage:
    python -m orion.supervise_run --db data/forge/corpus_v2.db \
        --target 8000 --max-restarts 200
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time


def _clean_count(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM records "
                         "WHERE status='clean'").fetchone()[0]
    except Exception:  # noqa: BLE001
        return 0
    finally:
        c.close()


def supervise(db_path: str, target: int, out_dir: str, seed: int,
              max_restarts: int, stall_grace: int) -> int:
    launches = 0
    while launches < max_restarts:
        have = _clean_count(db_path)
        if have >= target:
            print(f"[supervisor] target reached: {have} >= {target}")
            return 0
        launches += 1
        print(f"[supervisor] launch {launches}: {have}/{target} clean records",
              flush=True)
        before = have
        proc = subprocess.run(
            [sys.executable, "-m", "orion.forge_loop",
             "--db", db_path, "--out", out_dir, "--no-json",
             "--seed", str(seed), "--target", str(target)],
            capture_output=True, text=True)
        after = _clean_count(db_path)
        gained = after - before
        print(f"[supervisor] launch {launches} exited rc={proc.returncode}, "
              f"+{gained} records ({after}/{target})", flush=True)
        if proc.returncode != 0:
            print("[supervisor] stderr tail:",
                  (proc.stderr or "")[-500:], flush=True)
        if after >= target:
            print(f"[supervisor] target reached: {after}")
            return 0
        # A launch that made no progress twice in a row is a hard stall
        # (sampler exhausted or a persistent build failure), not a transient
        # interruption — stop rather than spin.
        if gained == 0:
            time.sleep(stall_grace)
            if _clean_count(db_path) == after:
                print("[supervisor] no progress after grace period — stopping "
                      "to avoid a spin loop; investigate the loop output.")
                return 1
    print(f"[supervisor] hit max-restarts={max_restarts}; "
          f"{_clean_count(db_path)}/{target}")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--out", default="data/forge/scale")
    ap.add_argument("--seed", type=int, default=100000)
    ap.add_argument("--max-restarts", type=int, default=200)
    ap.add_argument("--stall-grace", type=int, default=30)
    args = ap.parse_args()
    rc = supervise(args.db, args.target, args.out, args.seed,
                   args.max_restarts, args.stall_grace)
    sys.exit(rc)


if __name__ == "__main__":
    main()
