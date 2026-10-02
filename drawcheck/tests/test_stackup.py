import math

import pytest

from drawcheck.stackup import Link, link_from_text, stack


def test_worst_case_and_rss():
    # housing 50 ±0.1, minus shaft 49.8 ±0.05 -> gap 0.2
    r = stack([Link(50, 0.1, -0.1, 1), Link(49.8, 0.05, -0.05, -1)], min_gap=0.0)
    assert r.nominal == pytest.approx(0.2)
    assert r.worst_case_tol == pytest.approx(0.15)
    assert r.rss_tol == pytest.approx(math.hypot(0.1, 0.05), abs=1e-6)
    assert r.wc_min == pytest.approx(0.05) and r.wc_ok is True


def test_asymmetric_tolerance_uses_mean():
    r = stack([Link(20, 0.05, 0.0, 1)])
    assert r.mean == pytest.approx(20.025) and r.worst_case_tol == pytest.approx(0.025)


def test_failing_requirement():
    r = stack([Link(10, 0.2, -0.2, 1), Link(10, 0.2, -0.2, -1)], min_gap=0.0)
    assert r.wc_ok is False and r.wc_min == pytest.approx(-0.4)


def test_link_from_text():
    k = link_from_text("-20 +0.05/0")
    assert (k.direction, k.nominal, k.upper, k.lower) == (-1, 20.0, 0.05, 0.0)
    with pytest.raises(ValueError):
        link_from_text("+20")            # no tolerance: cannot be stacked
    with pytest.raises(ValueError):
        Link(10, -0.1, 0.1)              # reversed deviations
