"""Step 9: every seeded error is a test; the accuracy bar is a test.

Bar: recall >= 80% over the seeded set and at most 1 high/medium false alarm
on each clean assembly.
"""
import warnings

import pytest

from interface_check.bench import run
from interface_check.synth import MUTATIONS

warnings.filterwarnings("ignore", module="build123d")


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    return run(tmp_path_factory.mktemp("bench"))


def test_accuracy_bar(bench):
    assert bench["total"]["seeded"] >= 30
    assert bench["total"]["recall"] >= 0.8, [s for s in bench["seeded"] if not s["caught"]]
    assert bench["total"]["max_false_alarms_per_assembly"] <= 1, bench["clean"]


def test_clean_runs_make_no_llm_calls(bench):
    assert all(c["llm_calls"] == 0 for c in bench["clean"].values())


@pytest.mark.parametrize("mid", [m.id for m in MUTATIONS])
def test_seeded(bench, mid):
    s = next(x for x in bench["seeded"] if x["id"] == mid)
    assert s["caught"], f"{mid}: expected {s['expect']}, fired {s['fired']}"


def test_revision_change_impact(bench):
    s = next(x for x in bench["seeded"] if x["id"] == "rev_plate_holes")
    assert any("motor_plate" in c and "frame_bracket" in c and "NEMA17_motor" in c for c in s["changes"])
