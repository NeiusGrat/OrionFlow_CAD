"""§13.4: regression tests for the measured facts F1 and F2 (OF-TR-002 §3).
If these ever fail, something changed in build123d's STEP writer or in our
canonicalization, and every cache key in the system is suspect.
"""

import time

from build123d import Pos, Box, export_step

from orion_harness.execute.canonical import (
    canonicalize_step_text,
    geom_hash,
    geometric_signature,
    hash_step_bytes,
)


def _box():
    return Pos(0, 0, 0) * Box(10, 20, 5)


def test_f1_raw_step_bytes_differ_but_canonicalized_match(tmp_path):
    shape = _box()
    p1 = tmp_path / "a.step"
    p2 = tmp_path / "b.step"
    export_step(shape, str(p1))
    time.sleep(1.1)  # force the ISO-timestamp second to roll over
    export_step(shape, str(p2))

    raw1 = p1.read_bytes()
    raw2 = p2.read_bytes()

    # Raw bytes are allowed to differ (F1: FILE_NAME carries a timestamp).
    # This isn't asserted strictly equal-or-not because a sub-second export
    # could coincidentally land in the same second; what must hold is the
    # canonicalized hash below.
    canon1 = hash_step_bytes(raw1)
    canon2 = hash_step_bytes(raw2)
    assert canon1 == canon2, "canonicalized STEP hash must survive a re-export (F1)"


def test_f1_canonicalize_strips_only_the_timestamp():
    text = "FILE_NAME('part.step','2026-09-12T10:31:02',('author'),('org'),'','','');"
    canonical = canonicalize_step_text(text)
    assert "2026-09-12T10:31:02" not in canonical
    assert "'part.step'" in canonical  # filename field itself is untouched


def test_second_nondeterminism_source_found_in_this_environment(tmp_path):
    """Not in OF-TR-002 §3 F1 (measured on build123d 0.11.1/Linux): this
    repo's build123d 0.10.0 on Windows also varies
    NEXT_ASSEMBLY_USAGE_OCCURRENCE's first field, a process-global OCCT
    counter that increments on every export_step() call regardless of
    content. Confirmed by exporting the same shape three times in one
    process. Must also be canonicalized, or two exports in the same worker
    process (exactly what the rebuild-determinism gate does) never match."""

    shape = _box()
    paths = [tmp_path / f"c{i}.step" for i in range(3)]
    for p in paths:
        export_step(shape, str(p))

    raw = [p.read_text(encoding="utf-8") for p in paths]
    counters = [
        t.split("NEXT_ASSEMBLY_USAGE_OCCURRENCE('", 1)[1].split("'", 1)[0] for t in raw
    ]
    assert len(set(counters)) == 3, "expected the raw counter to differ across exports"

    canonical = [hash_step_bytes(t.encode("utf-8")) for t in raw]
    assert len(set(canonical)) == 1, "canonicalized hash must ignore the OCCT export counter"


def test_f2_geometric_signature_stable_across_rebuilds():
    shape_a = _box()
    shape_b = _box()
    sig_a = geometric_signature(shape_a)
    sig_b = geometric_signature(shape_b)
    assert sig_a == sig_b
    assert geom_hash(shape_a) == geom_hash(shape_b)


def test_f2_geometric_signature_differs_for_different_geometry():
    a = Pos(0, 0, 0) * Box(10, 20, 5)
    b = Pos(0, 0, 0) * Box(10, 20, 6)
    assert geom_hash(a) != geom_hash(b)
