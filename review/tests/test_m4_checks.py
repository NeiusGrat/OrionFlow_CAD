"""M4: D2 interfaces + D3 static clearance, with the seeded-error suite.

Seeded errors come from interface_check.synth.MUTATIONS — each variant carries
exactly one known error. Every one must be caught by the expected check, and
the clean assemblies must raise no interface or clearance finding at all.
"""
from __future__ import annotations

import math

import pytest

from review.checks import run_checks
from review.ingest import build_graph

MAP = {"HOLE_MISALIGNED": "IF-HOLE-ALIGN", "PATTERN_MISMATCH": "IF-PATTERN",
       "FASTENER_SIZE_MISMATCH": "IF-FASTENER-SIZE", "HOLE_MISSING": "IF-HOLE-ALIGN"}
D23 = ("interfaces", "clearance")


def _seeded():
    from interface_check.synth import MUTATIONS
    return [m for m in MUTATIONS if m.expect in MAP and m.prev is None]


def _findings(step):
    findings, runs = run_checks(build_graph(step, "t"))
    return [f for f in findings if f.domain in D23], runs


@pytest.mark.parametrize("assembly", ["motor_mount", "bearing_joint", "chassis"])
def test_clean_assemblies_raise_nothing(assembly, tmp_path):
    from interface_check.synth import build
    found, runs = _findings(build(assembly, {}, tmp_path)["step"])
    assert found == [], [(f.check_id, f.title) for f in found]
    assert all(r["status"] in ("passed", "not_run") for r in runs if r["domain"] in D23)


@pytest.mark.parametrize("m", _seeded(), ids=lambda m: m.id)
def test_seeded_error_is_caught(m, tmp_path):
    from interface_check.synth import build
    found, _ = _findings(build(m.assembly, m.params, tmp_path)["step"])
    hits = [f for f in found if f.check_id == MAP[m.expect]]
    assert hits, f"{m.id} ({m.note}) not caught; got {[(f.check_id, f.title) for f in found]}"
    others = {f.check_id for f in found} - {MAP[m.expect]}
    assert not others, f"{m.id}: unexpected extra checks fired: {others}"


def test_misalignment_is_measured(tmp_path):
    from interface_check.synth import build
    found, _ = _findings(build("motor_mount", {"corner_shift": (0, 1.0)}, tmp_path)["step"])
    (f,) = [x for x in found if x.check_id == "IF-HOLE-ALIGN"]
    assert f.measured.value == pytest.approx(1.0, abs=1e-3) and f.expected.max == 0.05
    assert {e.type for e in f.evidence} >= {"instance", "contact", "measurement"}


# --------------------------------------------------------------- fixtures --

def _step(tmp_path, name, parts):
    from build123d import Compound, export_step
    asm = Compound(children=parts)
    asm.label = name
    path = tmp_path / f"{name}.step"
    export_step(asm, str(path).replace("\\", "/"))
    return path


def _lbl(shape, name):
    shape.label = name
    return shape


def _bolt(d, head_d, shank, head_h, x=0.0, y=0.0, z0=0.0):
    """A headed bolt standing on z0: head below, shank up."""
    from build123d import Cylinder, Pos
    head = Pos(x, y, z0 - head_h / 2) * Cylinder(head_d / 2, head_h)
    body = Pos(x, y, z0 + shank / 2) * Cylinder(d / 2, shank)
    return head + body


def test_overlap_is_measured_exactly(tmp_path):
    from build123d import Box, Pos
    a = _lbl(Pos(0, 0, 5) * Box(20, 20, 10), "block_a")
    b = _lbl(Pos(15, 0, 5) * Box(20, 20, 10), "block_b")          # overlaps a by 5 x 20 x 10 = 1000 mm3
    found, _ = _findings(_step(tmp_path, "ovl", [a, b]))
    (f,) = [x for x in found if x.check_id == "CM-INTERFERENCE"]
    assert f.severity == "critical" and f.measured.value == pytest.approx(1000.0, rel=1e-6)


def test_modelled_thread_is_not_an_interference_but_a_press_fit_is_info(tmp_path):
    from build123d import Box, Cylinder, Pos
    plate = Pos(0, 0, 3) * Box(40, 20, 6) - Pos(-10, 0, 3) * Cylinder(1.25, 6) - Pos(10, 0, 3) * Cylinder(2.0, 6)
    plate = _lbl(plate, "base_plate")
    bolt = _lbl(_bolt(3.0, 5.5, 6.0, 3.0, x=-10, z0=0.0), "M3_bolt")        # M3 drawn at full size in a 2.5 tap hole
    pin = _lbl(Pos(10, 0, 3) * Cylinder(2.1, 6), "press_pin")                 # 4.2 pin in a 4.0 hole
    found, _ = _findings(_step(tmp_path, "thr", [plate, bolt, pin]))
    inter = [x for x in found if x.check_id == "CM-INTERFERENCE"]
    assert [x.severity for x in inter] == ["info"], [(x.title, x.statement) for x in inter]
    assert inter[0].title == "Interference fit by design" and inter[0].measured.value == pytest.approx(0.2, abs=1e-3)


@pytest.mark.parametrize("gap,want", [(0.08, "major"), (0.2, "minor"), (0.5, None)])
def test_min_clearance_thresholds(tmp_path, gap, want):
    from build123d import Box, Pos
    base = _lbl(Pos(0, 0, 5) * Box(40, 40, 10), "base")
    a = _lbl(Pos(0, 0, 12) * Box(10, 10, 4), "bracket")                       # sits on base (touching)
    b = _lbl(Pos(5 + gap + 5, 0, 12) * Box(10, 10, 4), "cover")               # on base too, `gap` from bracket
    found, _ = _findings(_step(tmp_path, f"gap{gap}", [base, a, b]))
    got = [x.severity for x in found if x.check_id == "CM-MIN-CLEARANCE"]
    assert got == ([want] if want else []), got


def test_floating_part(tmp_path):
    from build123d import Box, Pos
    base = _lbl(Pos(0, 0, 5) * Box(40, 40, 10), "base")
    sat = _lbl(Pos(0, 0, 13) * Box(10, 10, 6), "bracket")
    lost = _lbl(Pos(60, 0, 5) * Box(5, 5, 5), "stray_spacer")
    found, _ = _findings(_step(tmp_path, "float", [base, sat, lost]))
    (f,) = [x for x in found if x.check_id == "IF-CONTACT"]
    assert "stray_spacer" in f.statement and f.severity == "major"


def test_tight_clearance_under_a_bolt_head(tmp_path):
    from build123d import Box, Cylinder, Pos
    clamp = _lbl(Pos(0, 0, 3) * Box(20, 20, 6) - Pos(0, 0, 3) * Cylinder(2.05, 6), "clamp_plate")    # 4.1 for M4: tight
    base = _lbl(Pos(0, 0, -5) * Box(20, 20, 10) - Pos(0, 0, -5) * Cylinder(1.65, 10), "base_block")  # 3.3 M4 tap
    from build123d import Rot
    # flipped so the head (z 6..10) sits on the clamp and the shank (z -6..6) runs down into the tapped base
    bolt = _lbl(Pos(0, 0, 6) * Rot(180, 0, 0) * _bolt(4.0, 7.0, 12.0, 4.0, z0=0.0), "M4x12")
    found, _ = _findings(_step(tmp_path, "tight", [clamp, base, bolt]))
    tight = [x for x in found if x.check_id == "IF-FASTENER-SIZE"]
    assert len(tight) == 1, [(x.title, x.statement) for x in tight]
    t = tight[0]
    assert t.title == "Clearance hole is tight for its bolt" and t.severity == "major"
    assert t.measured.value == pytest.approx(4.1, abs=1e-3) and t.expected.min == 4.3
    assert "clamp_plate" in t.statement and "base_block" not in t.statement     # the threaded part is not judged
