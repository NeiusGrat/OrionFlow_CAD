"""Versions stamped on every result, cache entry and worker run.

ENGINE_VERSION changes when any rule's pass/fail logic changes: results from
two engine versions are not comparable, and the idempotency key includes it so
a re-run after an upgrade is a new job, not a cache replay.

EXTRACTION_VERSION changes when per-part feature extraction changes: it is part
of the geometry-cache key, so a new extractor never reads an old extractor's
features.
"""

ENGINE_VERSION = "ic-1.1.0"
EXTRACTION_VERSION = "fx-2"
