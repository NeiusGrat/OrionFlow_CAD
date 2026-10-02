"""Review memory: what a reviewer decided about each finding.

Two decisions, with different reach:
  accepted   the finding is real but the customer has accepted it (a known
             deviation, an in-house convention). It is suppressed on every
             later drawing for the same customer with the same rule and the
             same callout text.
  rejected   the checker was wrong (misread, wrong rule). Suppressed only on
             this exact finding (same fingerprint), and kept as a labelled
             error for measuring and training the reader.

SQLite, one file, no server: a shop can run this on one PC.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from .model import Finding, Report

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    finding_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    evidence TEXT NOT NULL,
    customer TEXT NOT NULL DEFAULT '',
    drawing TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    note TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dec_fid ON decisions(finding_id);
CREATE INDEX IF NOT EXISTS ix_dec_dev ON decisions(customer, rule, evidence);
"""


def norm_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().upper())


class Store:
    def __init__(self, path: str | Path = "drawcheck.sqlite"):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def decide(self, f: Finding, decision: str, customer: str = "", drawing: str = "",
               source: str = "", note: str = "", reviewer: str = "") -> None:
        if decision not in ("accepted", "rejected", ""):
            raise ValueError("decision must be 'accepted', 'rejected' or '' (undo)")
        with self._conn() as c:
            c.execute("DELETE FROM decisions WHERE finding_id = ? AND customer = ?", (f.id, customer))
            if decision:
                c.execute(
                    "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f.id, f.rule, norm_evidence(f.evidence), customer, drawing, source,
                     decision, note, reviewer, time.time()),
                )

    def apply(self, report: Report, customer: str = "") -> None:
        """Mark decided findings and move suppressed ones out of the open list."""
        with self._conn() as c:
            by_id = {r["finding_id"]: r["decision"] for r in c.execute(
                "SELECT finding_id, decision FROM decisions WHERE customer = ?", (customer,))}
            deviations = {(r["rule"], r["evidence"]) for r in c.execute(
                "SELECT rule, evidence FROM decisions WHERE customer = ? AND decision = 'accepted' "
                "AND evidence != ''", (customer,))}
        keep: list[Finding] = []
        for f in report.findings:
            dec = by_id.get(f.id)
            if dec:
                f.decision = dec
                (report.suppressed if dec == "rejected" else keep).append(f)
            elif f.evidence and (f.rule, norm_evidence(f.evidence)) in deviations:
                f.decision = "accepted"
                report.suppressed.append(f)
            else:
                keep.append(f)
        report.findings = keep

    def stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT rule, decision, COUNT(*) n FROM decisions GROUP BY rule, decision").fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["rule"], {})[r["decision"]] = r["n"]
        return out
