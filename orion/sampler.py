"""Topology sampler: which recipe next, and does the draw earn its place.

Two forces, both measured rather than hoped for:

* **Coverage** — recipes whose feature n-grams are RARE in the corpus so far
  get upweighted (inverse frequency), with a hard 10x boost while a target
  feature (Thickness/Draft/Sweep/Loft/patterns/dress-ups) has fewer than
  ``MIN_PER_FEATURE`` accepted parts. This is what stops the pilot from
  collapsing into fifty near-identical plates.

* **Diversity gate** — a draw is REJECTED before any build if its (volume,
  aspect-ratio) signature sits within 5% of an already-accepted part of the
  same recipe. Volume comes from the blueprint's own body_volume assertion,
  so the gate costs microseconds, not a FreeCAD run.

Shannon entropy over accepted feature sequences is the pilot health metric
(target > 2.0 bits over 8 recipes; the plan's 4-bit target presumes a wider
palette than the pilot ships with).
"""

from __future__ import annotations

import collections
import hashlib
import math
import os
import random
from typing import Any, Optional

from . import expr as E
from .bases import BASES
from .compose import compose, compose_faults
from .recipes import RECIPES


def _seq_hash(family: str, seq, attachments) -> str:
    return hashlib.sha256(
        ("|".join(seq) + "::" + family + "::"
         + ",".join(sorted(attachments))).encode()).hexdigest()[:16]

#: Features the corpus audit found empty; boosted until each has this many.
TARGET_FEATURES = ("Thickness", "Draft", "Fillet", "Chamfer",
                   "LinearPattern", "PolarPattern", "Mirrored",
                   "Sweep", "Loft", "Groove")
MIN_PER_FEATURE = 10
BOOST = 10.0
SIG_TOL = 0.05
#: Hard cap on records per TOPOLOGY signature. Without it the diversity gate
#: (which only blocks same-signature-AND-same-size) lets a fixed-topology
#: recipe accumulate ~80 pure size-variants, concentrating the record mass on a
#: handful of shapes and CRUSHING the entropy-weighted effective topology count
#: 2^H even as the raw distinct-signature count grows. Capping every signature
#: flattens the distribution so 2^H rises toward the distinct-topology ceiling —
#: the honest measure of verified topology diversity.
#:
#: Env-tunable so a small diversity-probe run keeps the tight default (10) while
#: a large SCALE run raises it: at scale the reachable-and-uncapped topology
#: space would otherwise exhaust and the run would starve well short of target
#: (the 4k v3 probe starved at ~3.1k at cap 10). A higher cap keeps drawing the
#: reachable topologies — each still bounded, so the distribution stays flat and
#: 2^H stays near the distinct-topology ceiling — until the record target is met.
PER_SIG_CAP = int(os.environ.get("ORION_SIG_CAP", "10"))
#: How many candidates draw() tries before giving up. Env-tunable because late
#: in a scale run most easy signatures are capped and the remaining capacity is
#: a long tail of rare (base, attachment-set) combos — more attempts per draw
#: reach that tail instead of the run starving with headroom still unfilled.
DRAW_ATTEMPTS = int(os.environ.get("ORION_DRAW_ATTEMPTS", "40"))


def _signature(bp) -> Optional[tuple]:
    """(body_volume, aspect ratios) predicted straight from the blueprint —
    the diversity gate must not require a build."""
    body = next((a for a in bp.assertions
                 if a.get("kind") == "body_volume"), None)
    vol = None
    if body and isinstance(body.get("target"), str):
        try:
            vol = E.evaluate(body["target"], bp.variables)
        except E.ExprError:
            vol = None
    dims = sorted(v for k, v in bp.variables.items()
                  if isinstance(v, (int, float)) and v > 0)
    if not dims:
        return None
    aspect = dims[-1] / dims[0]
    return (vol, aspect)


def _close(a: Optional[float], b: Optional[float], tol: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


class TopologySampler:
    def __init__(self, seed: int = 0, compose_p: float = 0.8):
        self.rng = random.Random(seed)
        self.compose_p = compose_p
        self.accepted_seqs: list[tuple] = []
        self.feature_counts: collections.Counter = collections.Counter()
        self.recipe_counts: collections.Counter = collections.Counter()
        self.signatures: dict[str, list[tuple]] = collections.defaultdict(list)
        self.rejected_similar = 0
        # Phase-5A diversity gate: a candidate is rejected only when its
        # TOPOLOGICAL SIGNATURE has been seen AND its volume/aspect are both
        # within 5%. Same shape at a genuinely different size is diversity;
        # same shape at the same size is a duplicate.
        self.sig_counts: collections.Counter = collections.Counter()
        self.sig_signatures: dict[str, list[tuple]] = \
            collections.defaultdict(list)
        # Per-signature CLEAN tally, the cap's source of truth. Incremented by
        # note_clean() the moment a caller commits a signature to a clean job —
        # BEFORE the batch builds, so the cap holds within a batch (accept()'s
        # sig_counts only updates after a whole batch finalizes). Only clean
        # jobs count: stress/injected variants share a signature but must not
        # consume its clean budget, or each shape starves at ~2-3 clean records.
        self.sig_drawn: collections.Counter = collections.Counter()
        self.rejected_capped = 0
        self.base_counts: collections.Counter = collections.Counter()
        self.attachment_counts: collections.Counter = collections.Counter()
        self.datum_counts: collections.Counter = collections.Counter()
        self._seq_cache: dict[str, tuple] = {}

    # ---- weighting ------------------------------------------------------- #
    def _recipe_weight(self, name: str, seq: tuple) -> float:
        # A monolithic recipe is essentially one topology, so once its single
        # signature is capped there is nothing more to gain from drawing it —
        # zero its weight so the recipe branch stops wasting attempts on it.
        if self.sig_drawn[_seq_hash(name, seq, [])] >= PER_SIG_CAP:
            return 1e-9
        w = 1.0 / (1.0 + self.recipe_counts[name])   # inverse frequency
        if any(f in TARGET_FEATURES
               and self.feature_counts[f] < MIN_PER_FEATURE
               for f in seq):
            w *= BOOST
        return w

    def _recipe_seq(self, name: str) -> tuple:
        # Feature sequences per recipe are stable modulo the optional groove /
        # bolt-circle branches; a probe draw is exact enough. CACHED: this is
        # called once per recipe per draw, and an uncached probe re-freezes
        # every recipe (sha256 + full static check + profile builds) on every
        # single draw — measured as the dominant non-FreeCAD cost of a run.
        if name in self._seq_cache:
            return self._seq_cache[name]
        probe = random.Random(1234)
        try:
            _bp, _f, seq = RECIPES[name](probe)
        except Exception:  # noqa: BLE001
            seq = ()
        self._seq_cache[name] = seq
        return seq

    # ---- sampling -------------------------------------------------------- #
    def _base_weight(self, name: str) -> float:
        return 1.0 / (1.0 + self.base_counts[name])

    def note_clean(self, sig_key: str) -> None:
        """Record that a signature has been committed to a CLEAN job. This is
        what the per-signature cap counts — call it once per clean job at the
        moment it is queued, never for stress/injected variants."""
        self.sig_drawn[sig_key] += 1

    def draw(self, max_attempts: Optional[int] = None):
        """Sample one novel candidate. Returns
        ``(blueprint, faults, seq, family, meta)`` or None.

        Two generators share the draw: monolithic recipes and the
        composition system (base + 0-3 attachments). Composition is where
        feature INTERACTION data comes from, so it takes the larger share.
        """
        if max_attempts is None:
            max_attempts = DRAW_ATTEMPTS
        for _ in range(max_attempts):
            use_compose = BASES and self.rng.random() < self.compose_p
            if use_compose:
                bnames = list(BASES)
                bw = [self._base_weight(n) for n in bnames]
                bname = self.rng.choices(bnames, weights=bw)[0]
                try:
                    draft = BASES[bname](self.rng)
                    bp, meta = compose(draft, self.rng)
                except ValueError:
                    continue          # infeasible draw, roll again
                except Exception:     # noqa: BLE001
                    continue
                seq = tuple(meta["feature_seq"])
                family = meta["base_family"]
                faults = compose_faults(meta)
            else:
                names = list(RECIPES)
                weights = [self._recipe_weight(n, self._recipe_seq(n))
                           for n in names]
                name = self.rng.choices(names, weights=weights)[0]
                try:
                    bp, faults, seq = RECIPES[name](self.rng)
                except Exception:  # noqa: BLE001
                    continue
                family = name
                meta = {"base_family": name, "attachments": [],
                        "datum_strategy": bp.datums,
                        "feature_sequence_hash": _seq_hash(name, seq, []),
                        "feature_seq": list(seq)}

            sig_key = meta["feature_sequence_hash"]
            # Hard per-signature cap: this topology already has enough records,
            # so any further draw of it is parameter expansion, not new
            # topology. Reject and roll for a different shape.
            if self.sig_drawn[sig_key] >= PER_SIG_CAP:
                self.rejected_capped += 1
                continue
            geo = _signature(bp)
            # Reject only on the full conjunction: same signature AND same
            # size AND same proportions.
            if geo is not None and any(
                    _close(geo[0], s[0], SIG_TOL)
                    and _close(geo[1], s[1], SIG_TOL)
                    for s in self.sig_signatures[sig_key]):
                self.rejected_similar += 1
                continue
            return bp, faults, seq, family, meta
        return None

    def accept(self, name: str, seq: tuple, bp, meta=None) -> None:
        self.recipe_counts[name] += 1
        self.accepted_seqs.append(tuple(seq))
        for f in seq:
            self.feature_counts[f] += 1
        geo = _signature(bp)
        if geo is not None:
            self.signatures[name].append(geo)
        if meta:
            sig_key = meta["feature_sequence_hash"]
            self.sig_counts[sig_key] += 1
            if geo is not None:
                self.sig_signatures[sig_key].append(geo)
            self.base_counts[meta["base_family"]] += 1
            for att in meta["attachments"]:
                self.attachment_counts[att] += 1
            self.datum_counts[str(sorted(meta["datum_strategy"].items()))] += 1

    # ---- metrics --------------------------------------------------------- #
    def entropy_bits(self) -> float:
        if not self.accepted_seqs:
            return 0.0
        counts = collections.Counter(self.accepted_seqs)
        n = len(self.accepted_seqs)
        return -sum((c / n) * math.log2(c / n) for c in counts.values())

    def coverage(self) -> dict[str, int]:
        return {f: self.feature_counts[f] for f in TARGET_FEATURES}

    def metrics(self) -> dict[str, Any]:
        vols = [s[0] for sigs in self.signatures.values() for s in sigs
                if s[0] is not None]
        cv = 0.0
        if len(vols) >= 2:
            mean = sum(vols) / len(vols)
            var = sum((v - mean) ** 2 for v in vols) / (len(vols) - 1)
            cv = math.sqrt(var) / mean if mean else 0.0
        return {
            "accepted": len(self.accepted_seqs),
            "entropy_bits": round(self.entropy_bits(), 3),
            "signature_entropy_bits": round(self.signature_entropy(), 3),
            "distinct_signatures": len(self.sig_counts),
            "volume_cv": round(cv, 3),
            "rejected_similar": self.rejected_similar,
            "rejected_capped": self.rejected_capped,
            "recipe_counts": dict(self.recipe_counts),
            "base_counts": dict(self.base_counts),
            "attachment_counts": dict(self.attachment_counts),
            "datum_counts": len(self.datum_counts),
            "feature_coverage": self.coverage(),
        }

    def signature_entropy(self) -> float:
        """Shannon entropy over TOPOLOGICAL SIGNATURES — the honest family
        count, immune to renaming one shape into several families."""
        if not self.sig_counts:
            return 0.0
        n = sum(self.sig_counts.values())
        return -sum((c / n) * math.log2(c / n)
                    for c in self.sig_counts.values())
