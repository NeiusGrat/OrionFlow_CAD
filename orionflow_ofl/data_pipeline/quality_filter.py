"""Filter training pairs for quality before fine-tuning.

Bad pairs hurt more than missing pairs.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter


class QualityFilter:
    """Filter and deduplicate training pairs."""

    def filter(self, pairs: list[dict]) -> list[dict]:
        """Remove bad pairs. Returns (filtered_list, stats_dict)."""
        stats: dict[str, int] = Counter()
        seen_hashes: set[str] = set()
        result: list[dict] = []

        for p in pairs:
            code = p.get("code", "")
            text = p.get("text", "")

            # 1. Exact (text + code) duplicate
            h = hashlib.md5((text + code).encode()).hexdigest()
            if h in seen_hashes:
                stats["exact_duplicate"] += 1
                continue
            seen_hashes.add(h)

            # 2. Missing required patterns
            if "from orionflow_ofl import" not in code:
                stats["missing_import"] += 1
                continue
            if "export(" not in code:
                stats["missing_export"] += 1
                continue

            # 3. Code too short (< 2 meaningful lines after import)
            meaningful = [
                ln for ln in code.splitlines()
                if ln.strip()
                and not ln.strip().startswith("#")
                and not ln.strip().startswith("from ")
                and not ln.strip().startswith("import ")
            ]
            if len(meaningful) < 2:
                stats["too_short_code"] += 1
                continue

            # 4. Code too long (> 60 lines)
            if len(code.splitlines()) > 60:
                stats["too_long_code"] += 1
                continue

            # 5. Text too short (< 3 words) or too long (> 120 words)
            word_count = len(text.split())
            if word_count < 3:
                stats["too_short_text"] += 1
                continue
            if word_count > 120:
                stats["too_long_text"] += 1
                continue

            result.append(p)

        stats["kept"] = len(result)
        stats["total_input"] = len(pairs)
        # attach stats for caller
        self._last_stats = dict(stats)
        return result

    @property
    def last_stats(self) -> dict:
        return getattr(self, "_last_stats", {})

    def balance_complexity(
        self, pairs: list[dict], max_per_complexity: int = 3000
    ) -> list[dict]:
        """Ensure balanced complexity distribution.

        Target distribution (rough):
            complexity 1: 20%
            complexity 2: 25%
            complexity 3: 30%
            complexity 4: 20%
            complexity 5:  5%
        """
        buckets: dict[int, list[dict]] = {i: [] for i in range(1, 6)}
        for p in pairs:
            c = p.get("complexity", 1)
            c = max(1, min(c, 5))
            buckets[c].append(p)

        # target fractions (of the total we want)
        total_target = sum(len(v) for v in buckets.values())
        fractions = {1: 0.20, 2: 0.25, 3: 0.30, 4: 0.20, 5: 0.05}

        balanced: list[dict] = []
        for c in range(1, 6):
            cap = min(max_per_complexity, int(total_target * fractions[c]) + 1)
            available = buckets[c]
            if len(available) > cap:
                random.shuffle(available)
                available = available[:cap]
            balanced.extend(available)

        random.shuffle(balanced)
        return balanced
