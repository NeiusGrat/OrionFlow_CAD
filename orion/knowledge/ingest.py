"""Invariant-gated ingestion: an LLM or a regex may transcribe, nothing lands unchecked.

Building the bearing catalogue by hand turned up two published tables that were
confidently wrong — one listing 6208 as 40x80x15 when it is 18, and an ISO 286
extraction misaligned by a row. Both were plausible. Both would have shipped
silently and produced parts that assemble wrongly with nothing to indicate it.

So the rule for every component family we add is the same: extraction proposes,
an invariant disposes. A row enters the catalogue only if it satisfies
properties the data must have for structural reasons — not because a parser
believed it.

Three kinds of invariant, in descending order of strength:

* **Derivable column.** The best kind. When a table prints a value a formula can
  also produce, check them against each other: SKF prints every dimension in
  both mm and inches, so ``d_in == d_mm/25.4`` proves the columns did not shift.
  Agreement validates the transcription *and* the formula at once.
* **Structural.** Properties of the series: dimensions increase with size code,
  and for codes >= 04 the bore is the code times five.
* **Physical.** Bounds nothing real can leave: a bearing's bore is smaller than
  its outside diameter, a load rating is positive.

Rows that fail are not discarded quietly — they are returned with the invariant
they broke, so a bad page is visible rather than merely absent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

#: A check over one parsed row. Returns None when satisfied, else the reason.
Invariant = Callable[[dict], Optional[str]]


@dataclass
class Rejection:
    row: dict
    reason: str

    def __str__(self) -> str:
        ident = self.row.get("designation") or self.row.get("id") or "?"
        return f"{ident}: {self.reason}"


@dataclass
class Harvest:
    """What an ingestion run produced, with the failures kept."""

    accepted: list[dict] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    source: str = ""
    pages: list[int] = field(default_factory=list)

    @property
    def rate(self) -> float:
        total = len(self.accepted) + len(self.rejected)
        return 100.0 * len(self.accepted) / total if total else 0.0

    def report(self) -> str:
        lines = [f"{len(self.accepted)} accepted, {len(self.rejected)} rejected "
                 f"({self.rate:.1f}% pass) from {self.source}"]
        for r in self.rejected[:12]:
            lines.append(f"  REJECTED {r}")
        if len(self.rejected) > 12:
            lines.append(f"  ... and {len(self.rejected) - 12} more")
        return "\n".join(lines)


def gate(rows: Iterable[dict], invariants: list[Invariant],
         source: str = "", pages: Optional[list[int]] = None,
         soft: Optional[list[tuple[Invariant, tuple[str, ...]]]] = None
         ) -> Harvest:
    """Run every invariant over every row. First hard failure rejects the row.

    ``soft`` invariants each guard a group of fields rather than the whole row.
    When one fails, those fields are dropped and the row is kept, because facts
    in a table are independent: a bearing whose millimetre and inch dimensions
    agree has correct dimensions whether or not the load-rating column beside
    them was extracted cleanly. Rejecting the row would discard verified
    geometry for an unrelated reason; keeping the rating would be worse. The
    drop is recorded on the row so nothing silently appears complete.
    """
    harvest = Harvest(source=source, pages=list(pages or []))
    for row in rows:
        for check in invariants:
            reason = check(row)
            if reason:
                harvest.rejected.append(Rejection(row, reason))
                break
        else:
            for check, fields in (soft or []):
                reason = check(row)
                if reason:
                    for field_name in fields:
                        row.pop(field_name, None)
                    row.setdefault("dropped", []).append(
                        f"{'/'.join(fields)}: {reason}")
            harvest.accepted.append(row)
    return harvest


# --------------------------------------------------------------------------- #
# reusable invariants
# --------------------------------------------------------------------------- #
def mm_inch_agree(mm_key: str, inch_key: str, tol: float = 0.002) -> Invariant:
    """The strongest check available on a dual-unit table.

    A catalogue that prints millimetres and inches side by side is carrying its
    own checksum: if a parser drifts by a column, the pair stops agreeing. This
    is what makes automated extraction from these documents safe.
    """
    def check(row: dict) -> Optional[str]:
        mm, inch = row.get(mm_key), row.get(inch_key)
        if mm is None or inch is None:
            return f"missing {mm_key}/{inch_key}"
        expected = float(mm) / 25.4
        if abs(float(inch) - expected) > tol:
            return (f"{mm_key}={mm} implies {inch_key}={expected:.4f} but the "
                    f"table says {inch} — the columns are misaligned")
        return None
    return check


def positive(*keys: str) -> Invariant:
    def check(row: dict) -> Optional[str]:
        for key in keys:
            value = row.get(key)
            if value is None:
                return f"missing {key}"
            if float(value) <= 0:
                return f"{key}={value} must be positive"
        return None
    return check


def ordered(smaller: str, larger: str) -> Invariant:
    def check(row: dict) -> Optional[str]:
        a, b = row.get(smaller), row.get(larger)
        if a is None or b is None:
            return f"missing {smaller}/{larger}"
        if not float(a) < float(b):
            return f"{smaller}={a} is not less than {larger}={b}"
        return None
    return check


def designation_encodes_bore(designation_key: str = "designation",
                             bore_key: str = "d") -> Invariant:
    """For metric series codes >= 04 the bore is the code times five.

    A structural property of the ISO designation system, and a direct check that
    a row's identity matches its dimensions.
    """
    def check(row: dict) -> Optional[str]:
        text = str(row.get(designation_key, ""))
        match = re.match(r"^\d{4}$", text)
        if not match:
            return None                      # not a plain 4-digit designation
        code = int(text[2:])
        if code < 4:
            return None                      # 00..03 are 10/12/15/17 mm
        expected = code * 5
        if abs(float(row.get(bore_key, -1)) - expected) > 1e-9:
            return (f"designation {text} implies a {expected} mm bore but the "
                    f"row says {row.get(bore_key)}")
        return None
    return check


def within(key: str, lo: float, hi: float) -> Invariant:
    def check(row: dict) -> Optional[str]:
        value = row.get(key)
        if value is None:
            return f"missing {key}"
        if not lo <= float(value) <= hi:
            return f"{key}={value} outside the physical range {lo}..{hi}"
        return None
    return check


def series_monotonic(rows: list[dict], series_of: Callable[[dict], str],
                     order_of: Callable[[dict], float],
                     keys: tuple[str, ...] = ("d", "D", "B")) -> list[Rejection]:
    """Cross-row check: dimensions grow with size code within a series.

    Runs after the per-row gate because it needs the whole set. This is the
    check that catches the 6208-as-15mm class of error, which every per-row
    invariant passes happily.
    """
    out: list[Rejection] = []
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(series_of(row), []).append(row)
    for _series, group in grouped.items():
        group.sort(key=order_of)
        for prev, cur in zip(group, group[1:]):
            for key in keys:
                if key in prev and key in cur and float(cur[key]) < float(prev[key]):
                    out.append(Rejection(cur, (
                        f"{key}={cur[key]} is smaller than "
                        f"{prev.get('designation')}'s {key}={prev[key]}; the "
                        f"series is not monotonic, which means a transcription "
                        f"error")))
    return out


# --------------------------------------------------------------------------- #
def write_catalogue(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
