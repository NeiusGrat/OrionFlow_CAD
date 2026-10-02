import pytest

from drawcheck import parse


@pytest.mark.parametrize("text,tol_type,upper,lower", [
    ("50 ±0.1", "symmetric", 0.1, -0.1),
    ("50 +/-0.1", "symmetric", 0.1, -0.1),
    ("10 +0.1/-0.05", "bilateral", 0.1, -0.05),
    ("10 +0.1 0", "bilateral", 0.1, 0.0),
    ("10 0/-0.2", "bilateral", 0.0, -0.2),
    ("10 -0.1/+0.05", "bilateral", -0.1, 0.05),     # written upside down: kept as written
    ("Ø30 +0.021/0", "bilateral", 0.021, 0.0),
    ("10.05/10.00", "limits", 0.0, -0.05),
    ("12,5 ±0,1", "symmetric", 0.1, -0.1),          # European decimal comma
    ("30° ±0.5°", "symmetric", 0.5, -0.5),
    ("100 MAX", "max", None, None),
    ("25", "none", None, None),
])
def test_dimension_tolerances(text, tol_type, upper, lower):
    d = parse.parse_dimension(text)
    assert d is not None
    assert (d["tol_type"], d["upper"], d["lower"]) == (tol_type, upper, lower)


def test_dimension_prefixes_and_counts():
    d = parse.parse_dimension("4X Ø6.6 THRU")
    assert (d["count"], d["prefix"], d["nominal"], d["suffix"]) == (4, "Ø", 6.6, "THRU")
    assert parse.parse_dimension("(25)")["reference"] is True
    assert parse.parse_dimension("Ø12H7/g6")["fit"] == "H7/g6"
    assert parse.parse_dimension(".500")["raw_nominal"] == ".500"


@pytest.mark.parametrize("text", ["1:2", "SHEET 1", "10 0/0", "(25", "10/2", "ABC"])
def test_not_dimensions(text):
    assert parse.parse_dimension(text) is None


def test_fits():
    assert parse.check_fit("H7/g6") == []
    assert parse.check_fit("H7") == []
    assert parse.check_fit("g6/H7")
    assert parse.check_fit("Q7")
    assert parse.check_fit("H19")


@pytest.mark.parametrize("text,system,cls,depth", [
    ("M8x1.25-6H", "metric", "6H", None),
    ("4X M6-6H ↧12", "metric", "6H", 12.0),
    ("M10", "metric", None, None),
    ("1/4-20 UNC-2B", "unified", "2B", None),
    ("1/4-20 UNC", "unified", None, None),
    ("G1/4", "pipe", None, None),
    ("1/4-18 NPT", "pipe", None, None),
])
def test_threads(text, system, cls, depth):
    t = parse.parse_thread(text)
    assert (t["system"], t["class"], t["depth"]) == (system, cls, depth)


@pytest.mark.parametrize("text,char,cat,datums,material,tol", [
    ("⌖ Ø0.1 Ⓜ A B C", "position", "location", ["A", "B", "C"], "M", 0.1),
    ("⟂ 0.05 A", "perpendicularity", "orientation", ["A"], None, 0.05),
    ("▱ 0.02", "flatness", "form", [], None, 0.02),
    ("2X ⌖ Ø0.2 A-B", "position", "location", ["A-B"], None, 0.2),
    ("⟂|0.05|A", "perpendicularity", "orientation", ["A"], None, 0.05),
])
def test_frames(text, char, cat, datums, material, tol):
    f = parse.parse_fcf(text)
    assert (f["characteristic"], f["category"], f["datums"], f["material"], f["tolerance"]) == \
        (char, cat, datums, material, tol)


def test_frame_refuses_garbage():
    assert parse.parse_fcf("⌖ Ø0.1 A something else") is None
    assert parse.parse_fcf("⌖ A B") is None            # no tolerance value


def test_gdt_font_translation():
    assert parse.translate_gdt_font("j") == "⌖"
    assert parse.parse_fcf(parse.translate_gdt_font("j") + " Ø0.1 Ⓜ A")["characteristic"] == "position"


@pytest.mark.parametrize("text,std,lin,geo", [
    ("GENERAL TOLERANCES ISO 2768-mK", "ISO 2768", "m", "K"),
    ("ISO 2768-1 m", "ISO 2768", "m", None),
    ("TOLERANCES PER ISO 2768", "ISO 2768", None, None),
    ("IS 2102 medium", "IS 2102", "m", None),
    ("TOLERANCES UNLESS OTHERWISE SPECIFIED X.X ±0.1", "block", None, None),
])
def test_general_tolerance(text, std, lin, geo):
    g = parse.parse_general_tolerance(text)
    assert (g["standard"], g["linear_class"], g["geometric_class"]) == (std, lin, geo)


def test_statements():
    assert parse.parse_projection("FIRST ANGLE PROJECTION") == "first"
    assert parse.parse_projection("3RD ANGLE") == "third"
    assert parse.parse_units("ALL DIMENSIONS IN MM") == "mm"
    assert parse.parse_units("DIMENSIONS IN INCHES") == "inch"
    assert parse.find_standards("PER ASME Y14.5-2018") == [{"standard": "ASME Y14.5", "year": "2018"}]
    assert parse.match_label("DWG NO: 1234") == ("drawing_number", "1234")
    assert parse.match_label("REVISION") == ("revision", "")
    assert parse.match_label("REVERSE SIDE") is None


def test_surface():
    assert parse.parse_surface("Ra 1.6") == {"param": "Ra", "value": 1.6}
    assert parse.parse_surface("N7") is None                       # N grades only in a finish context
    assert parse.parse_surface("ROUGHNESS N7", finish_context=True)["value"] == 1.6
