"""End to end on synthetic drawings with known defects: PDF -> findings."""
import pytest

from drawcheck import check_file, samples

pytestmark = pytest.mark.skipif(samples.symbol_font() is None, reason="no font with GD&T glyphs")


@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    samples.make_all(d)
    return d


@pytest.mark.parametrize("name", list(samples.EXPECTED))
def test_expected_rules(sample_dir, name):
    report, _ = check_file(sample_dir / f"{name}.pdf", vision="off")
    fired = {f.rule for f in report.findings}
    for rule, must in samples.EXPECTED[name].items():
        assert (rule in fired) == must, f"{name}: {rule} {'missing' if must else 'false positive'}; fired={sorted(fired)}"


def test_clean_drawing_reads_everything(sample_dir):
    report, d = check_file(sample_dir / "clean.pdf", vision="off")
    assert report.findings == []
    assert report.title["drawing_number"] == "OF-1001"
    assert report.title["material"] == "EN8 (080M40)"
    dims = {a.text: a.data for a in d.of("dimension")}
    assert dims["Ø30 +0.021/0"]["upper"] == 0.021          # stacked tolerance merged top-first
    assert dims["160"]["basic"] and dims["80"]["basic"]     # boxed numbers are basic dimensions
    assert {a.data["letter"] for a in d.of("datum_feature")} == {"A", "B", "C"}
    frames = {a.data["characteristic"]: a.data for a in d.of("gdt_frame")}
    assert frames["position"]["datums"] == ["A", "B", "C"] and frames["position"]["material"] == "M"
    # border zone labels and the title block are never read as dimensions
    assert not any(a.text in ("1", "2", "8", "2026-10-01", "1:2") for a in d.of("dimension"))


def test_findings_point_at_callouts(sample_dir):
    report, _ = check_file(sample_dir / "defective.pdf", vision="off")
    gd1 = next(f for f in report.findings if f.rule == "GD-001")
    assert gd1.page == 0 and gd1.bbox is not None
    assert "datum C" in gd1.query
    assert gd1.confidence == "vector"


def test_scanned_page_is_not_silently_passed(sample_dir):
    report, d = check_file(sample_dir / "scanned.pdf", vision="off")
    assert d.scanned_pages == [0]
    assert any(f.rule == "RD-001" for f in report.findings)
    # absence findings on an unread page are marked as unproven
    assert all(f.confidence == "partial" for f in report.findings if f.rule in ("TB-001", "PR-001"))
