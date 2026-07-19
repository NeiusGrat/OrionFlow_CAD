"""Mine repair-training data from production telemetry (ofl_events).

Emits chat-format rows teaching the model to FIX broken OFL given the
sandbox traceback — the behavior our harness's repair loop needs:

  system: repair instructions
  user:   original prompt + failing code + error
  assistant: corrected code

Sources:
  1. repair_trace rows (persisted from 2026-07-19 on): every self-repair
     step becomes a (bad code, error) -> fixed-code pair — the good stuff.
  2. Legacy failure rows (success=false, no trace): emitted to
     repair_diagnose.jsonl for future manual/model repair, not training.

Usage:
    python scripts/mine_repair_pairs.py
Outputs: freecad/variants/repair_chat.jsonl + repair_diagnose.jsonl
"""

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "freecad" / "variants"

REPAIR_SYSTEM = (
    "You are OrionFlow, a parametric CAD assistant. The OFL code below "
    "failed to execute. Read the error, fix the code, and output ONLY the "
    "corrected OFL program."
)


def _env() -> dict:
    env = {}
    for line in open(ROOT / "deploy" / ".env.deploy", encoding="utf-8"):
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2)
    return env


async def mine() -> dict:
    import asyncpg

    env = _env()
    conn = await asyncpg.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), user=env["DB_USER"],
        password=env["DB_PASSWORD"], database=env["DB_NAME"], ssl="require",
        statement_cache_size=0,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_triples = n_diag = 0

    # 1. Real repair triples from the persisted traces.
    rows = await conn.fetch(
        "select prompt, ofl_code, repair_trace from ofl_events "
        "where repair_trace is not null and success = true"
    )
    with open(OUT_DIR / "repair_chat.jsonl", "w", encoding="utf-8") as out:
        for r in rows:
            trace = json.loads(r["repair_trace"]) if isinstance(
                r["repair_trace"], str) else r["repair_trace"]
            fixed = r["ofl_code"]
            if not trace or not fixed:
                continue
            # Chain: attempt_i fails -> attempt_{i+1} (or the final code) fixes it.
            steps = list(trace) + [{"code": fixed, "error": None}]
            for bad, good in zip(steps, steps[1:]):
                if not bad.get("error") or not good.get("code"):
                    continue
                user = (
                    f"Original request: {r['prompt'] or '(unknown)'}\n\n"
                    f"Failing OFL code:\n{bad['code']}\n\n"
                    f"Error:\n{bad['error']}"
                )
                out.write(json.dumps({"messages": [
                    {"role": "system", "content": REPAIR_SYSTEM},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": good["code"]},
                ]}) + "\n")
                n_triples += 1

    # 2. Legacy hard failures — diagnosis backlog, not training data.
    rows = await conn.fetch(
        "select created_at, prompt, ofl_code, error from ofl_events "
        "where success = false and ofl_code is not null"
    )
    with open(OUT_DIR / "repair_diagnose.jsonl", "w", encoding="utf-8") as out:
        for r in rows:
            out.write(json.dumps({
                "created_at": str(r["created_at"]),
                "prompt": r["prompt"],
                "ofl_code": r["ofl_code"],
                "error": r["error"],
            }) + "\n")
            n_diag += 1

    await conn.close()
    summary = {"repair_triples": n_triples, "diagnose_backlog": n_diag,
               "out_dir": str(OUT_DIR)}
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    asyncio.run(mine())
