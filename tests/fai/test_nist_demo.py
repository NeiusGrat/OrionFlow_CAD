"""AP242 semantic-PMI answer key, reader scoring, inch drawings, and the NIST demos.

The NIST tests run only when the demo kit has been prepared
(``python -m fai.demo prepare``); the parser and scoring tests always run.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fai.score import score
from fai.step_pmi import parse_entities, read

AP242 = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }'));
ENDSEC;
DATA;
#1=(CONVERSION_BASED_UNIT('INCH',#2) LENGTH_UNIT() NAMED_UNIT(#3));
#2=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#4);
#4=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#10=DIMENSIONAL_SIZE(#90,'diameter');
#11=DIMENSIONAL_CHARACTERISTIC_REPRESENTATION(#10,#12);
#12=SHAPE_DIMENSION_REPRESENTATION('',(#13),#99);
#13=(LENGTH_MEASURE_WITH_UNIT() MEASURE_REPRESENTATION_ITEM() MEASURE_WITH_UNIT(LENGTH_MEASURE(0.25),#1)
 REPRESENTATION_ITEM('nominal value'));
#14=PLUS_MINUS_TOLERANCE(#15,#10);
#15=TOLERANCE_VALUE(#16,#17);
#16=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(-0.0),#1);
#17=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.003),#1);
#20=DATUM('','',#98,.F.,'A');
#21=DATUM('','',#98,.F.,'B');
#22=DATUM_REFERENCE_COMPARTMENT('',$,#98,.F.,#20,$);
#23=DATUM_REFERENCE_COMPARTMENT('',$,#98,.F.,#21,$);
#24=DATUM_SYSTEM('',$,#98,.F.,(#22,#23));
#30=(GEOMETRIC_TOLERANCE('FCF','',#31,#90)
 GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((#24))
 GEOMETRIC_TOLERANCE_WITH_MODIFIERS((.MAXIMUM_MATERIAL_REQUIREMENT.))
 POSITION_TOLERANCE());
#31=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.02),#1);
#32=TOLERANCE_ZONE('','',#98,.F.,(#30),#33);
#33=TOLERANCE_ZONE_FORM('cylindrical or circular');
ENDSEC;
END-ISO-10303-21;
"""


def test_ap242_parser_reads_dimension_tolerance_and_gdt(tmp_path):
    p = tmp_path / "part.stp"
    p.write_text(AP242, encoding="latin-1")
    ents = parse_entities(AP242)
    assert {x.name for x in ents[30]} >= {"GEOMETRIC_TOLERANCE", "POSITION_TOLERANCE"}
    k = read(p)
    assert k["units"] == "in" and k["datums"] == ["A", "B"]
    d = k["dimensions"][0]
    assert (d["type"], d["nominal"], d["lower"], d["upper"]) == ("Diameter", 0.25, -0.0, 0.003)
    assert d["nominal_mm"] == pytest.approx(6.35)
    g = k["gdt"][0]
    assert (g["type"], g["tolerance"], g["diameter_zone"], g["material"], g["datums"]) == \
        ("position", 0.02, True, "M", ["A", "B"])


def test_scoring_compares_in_millimetres(tmp_path):
    p = tmp_path / "part.stp"
    p.write_text(AP242, encoding="latin-1")
    key = read(p)
    chars = [
        {"no": 1, "kind": "dimension", "type": "Diameter", "nominal": 0.25, "tol_minus": 0.0, "tol_plus": 0.003,
         "unit": "in", "count": 1, "designator": "Ø.250 +.003/-.000", "requirement": "", "inspect": True},
        {"no": 2, "kind": "gdt", "type": "Position", "upper": 0.02, "unit": "in", "count": 1,
         "designator": "⌖ Ø.020 Ⓜ A B", "requirement": "Position within Ø0.02 in to datums A-B at MMC", "inspect": True},
    ]
    s = score(chars, key)
    assert (s["matched"], s["partial"], s["missed"], s["extra"]) == (2, 0, 0, [])
    chars[0]["unit"] = "mm"            # same digits read as millimetres must NOT score
    assert score(chars, key)["rows"][0]["status"] == "missed"


# ------------------------------------------------------------------ NIST kit (optional)

KIT = Path("data/nist_demo/kit")
needs_kit = pytest.mark.skipif(not (KIT / "demo2" / "FTC-07_revB_PLANTED.pdf").exists(),
                               reason="NIST demo kit not prepared (python -m fai.demo prepare)")


@pytest.fixture(scope="module")
def ftc07():
    from fai.pipeline import run

    k = KIT / "demo2"
    a = run(k / "FTC-07_revA.pdf", k / "FTC-07_model_AP242.stp", None, {}, tempfile.mkdtemp())
    b = run(k / "FTC-07_revB_PLANTED.pdf", k / "FTC-07_model_AP242.stp", None, {}, tempfile.mkdtemp())
    return a, b


@needs_kit
def test_inch_drawing_agrees_with_its_model(ftc07):
    a, _ = ftc07
    dias = [c for c in a["characteristics"] if c["type"] == "Diameter" and c["tol_source"] == "drawing"]
    assert dias and all(c["unit"] == "in" for c in dias)
    assert all(c["cad_status"] in ("agrees", "count") for c in dias)
    assert not [f for f in a["findings"] if f["kind"] == "cad" and f["severity"] in ("critical", "major")]
    assert a["accuracy"]["total"] >= 40 and a["accuracy"]["recall_with_partial"] >= 0.6


@needs_kit
def test_every_planted_error_is_caught(ftc07):
    from fai.compare import compare

    a, b = ftc07
    before = {(f["rule"], f["message"]) for f in a["findings"]}
    new = [f for f in b["findings"] if (f["rule"], f["message"]) not in before]
    rules = {f["rule"] for f in new}
    assert "GD-001" in rules                       # undefined datum Z
    assert "DM-001" in rules                       # reversed limits
    assert "CAD-DIA" in rules                      # Ø.938 on the drawing, Ø.875 in the model
    assert sum(f["rule"] == "FAI-TOL" for f in new) >= 3   # deleted tolerance + note removed
    diff = compare(a["characteristics"], b["characteristics"])
    assert diff["counts"]["changed"] >= 5 and diff["counts"]["added"] == 0 and diff["counts"]["removed"] == 0


@needs_kit
def test_shifted_cover_is_flagged_and_seated_cover_is_clean():
    from interface_check.pipeline import run_check

    clean = run_check(KIT / "demo3" / "box_cover_assembly.step").to_dict()
    assert clean["stats"]["interfaces"] >= 1 and not [f for f in clean["findings"] if f["severity"] in ("high", "medium")]
    shifted = run_check(KIT / "demo3" / "box_cover_assembly_SHIFTED_1mm.step").to_dict()
    f = next(f for f in shifted["findings"] if f["severity"] == "high")
    assert f["rule_id"] in ("PATTERN_MISMATCH", "HOLE_MISALIGNED")
    assert f["measured"].get("centre_offset_mm") == pytest.approx(1.0, abs=0.01)
