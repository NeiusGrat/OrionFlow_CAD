"""M5: BOM parsing, matching, materials, DOC-BOM-CAD (seeded), the engineer's links, export."""
from __future__ import annotations

import io

import pytest

from review.bom import apply, export_rows, parse, reconcile, score
from review.checks import run_checks
from review.ingest import build_graph
from review.materials import density, process_from_type

# the YUBI BOM's real layout (title row, separator, empty row, then the header), trimmed
YUBI_MD = b"""# csv\xe2\x86\x92md

| YUBI Gripper Assy_DYNAMIXEL_ver.2_PARTS LIST |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |
| No. | PART No. | TYPE | PART NAME | Qty. | MATERIAL |
| 1 | CASE | 3D-PRINTED | CASE | 1 | PLA_BLACK |
| 2 | FINGER PAD_t20 | 3D-PRINTED | FINGER PAD_t20 | 1 | PLA_RED |
| 3 | CB2.5-15 | STANDARD | CAP BOLT | 7 | SCM435 |
| 4 | JPBPB2-3 | STANDARD | PIN, LOCATING | 1 | SKS3 |
| 5 | JPBPB2-3 | STANDARD | PIN, LOCATING | 1 | SKS3 |
| 6 | [X-1](https://example.com/x) | STANDARD | THING | 2 | A2024 / PLA_BLACK |
|  |  |  |  |  |  | Note:
These links are provided for convenience only. Toyota does not endorse specific vendors or guarantee the quality. |
"""


def test_markdown_header_found_below_titles_and_footer_skipped():
    rows, info = parse("bom.md", YUBI_MD)
    assert info["header_row"] == 3 and info["columns"]["part_number"] == "PART No."
    assert [r.part_number for r in rows] == ["CASE", "FINGER PAD_t20", "CB2.5-15", "JPBPB2-3", "JPBPB2-3", "X-1"]
    assert rows[2].quantity == 7 and rows[2].material == "SCM435" and rows[2].type == "STANDARD"
    assert rows[5].part_number == "X-1"                            # markdown link text kept


def test_csv_and_xlsx():
    csv_rows, _ = parse("b.csv", b"Part Number,Description,Qty\nP-1,plate,2\nP-2,bolt,8\n")
    assert [(r.part_number, r.quantity) for r in csv_rows] == [("P-1", 2), ("P-2", 8)]
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Engineering BOM rev C"])
    ws.append([])
    ws.append(["Item", "Part No", "Name", "Quantity"])
    ws.append([1, "P-9", "shaft", 3])
    buf = io.BytesIO()
    wb.save(buf)
    x_rows, info = parse("b.xlsx", buf.getvalue())
    assert info["header_row"] == 3 and [(r.part_number, r.quantity) for r in x_rows] == [("P-9", 3)]


def test_no_header_is_an_error():
    with pytest.raises(ValueError):
        parse("x.csv", b"hello\nworld\n")


def test_fuzzy_subset_match_is_guarded():
    assert score("FINGER PAD_t30_R", "PAD_t30_R") == 100          # a prefix dropped
    assert score("FINGER PAD", "PAD") < 90                         # one generic token never matches
    assert score("RUBBER SHEET_L", "RUBBER SHEET_t20") < 90        # same family, different part: left for a human


def test_materials_and_processes():
    assert density("PLA_BLACK")[0] == 1240 and density("A2024")[0] == 2780 and density("SUS304")[0] == 7930
    assert density("SCM435")[0] == 7850 and density("brass")[0] == 8500
    assert density("A2024 / PLA_BLACK")[0] is None and "two materials" in density("A2024 / PLA_BLACK")[1]
    assert density("HYPER V SHEET")[0] is None and density("N/A")[0] is None
    assert process_from_type("3D-PRINTED") == "FDM" and process_from_type("MACHINED") == "CNC"
    assert process_from_type("MACHINED OR PRINTED") == "CNC or FDM" and process_from_type("STANDARD") == "purchased"


# ------------------------------------------------------------- chassis BOM --

@pytest.fixture(scope="module")
def chassis(tmp_path_factory):
    from interface_check.synth import build
    out = build("chassis", {}, tmp_path_factory.mktemp("ch"))
    return out, build_graph(out["step"], "t", analyse=False)


def _doc(graph):
    return [f for f in run_checks(graph)[0] if f.check_id == "DOC-BOM-CAD"]


def _with_bom(graph, text: bytes):
    g = graph.model_copy(deep=True)
    rows, _ = parse("bom.csv", text)
    apply(g, reconcile(rows, g))
    return g


def test_clean_bom_matches_and_counts(chassis):
    out, g0 = chassis
    g = _with_bom(g0, out["bom"].read_bytes())
    by_pn = {r["part_number"]: r for r in g.bom_rows}
    assert by_pn["BR-002"]["method"] == "exact" and by_pn["HW-010"]["method"] == "exact"
    found = _doc(g)
    # the clean BOM also orders M3 and M5 screws the CAD does not model: hardware, so minor
    assert sorted((f.title, f.severity) for f in found) == [("BOM row has no part in the CAD", "minor")] * 2
    plate = next(p for p in g.parts if p.name == "chassis_plate")
    assert plate.material == "Aluminium 6061" and plate.mass == pytest.approx(plate.volume * 1e-9 * 2700, abs=1e-6)   # stored to the milligram


SEEDED = {
    "ch_bom_drop_bracket": ("CAD part has no BOM row", "side_bracket"),
    "ch_bom_qty_standoff": ("BOM quantity differs from the assembly", "standoff_M3x35"),
    "ch_bom_qty_bracket": ("BOM quantity differs from the assembly", "side_bracket"),
    "ch_bom_add_camera": ("BOM row has no part in the CAD", "camera_mount"),
    "ch_bom_drop_standoff": ("CAD part has no BOM row", "standoff_M3x35"),
}


@pytest.mark.parametrize("mid", sorted(SEEDED))
def test_seeded_bom_errors(chassis, mid):
    from interface_check.synth import MUTATIONS, chassis_bom
    m = next(x for x in MUTATIONS if x.id == mid)
    _, g0 = chassis
    clean = {(f.title, f.statement) for f in _doc(_with_bom(g0, chassis_bom({}).encode()))}
    found = _doc(_with_bom(g0, chassis_bom(m.params).encode()))
    new = [f for f in found if (f.title, f.statement) not in clean]
    title, part = SEEDED[mid]
    assert any(f.title == title and part in f.statement for f in new), [(f.title, f.statement) for f in new]
    assert all(f.severity in ("major", "minor") for f in new)


def test_typos_still_match(chassis):
    from interface_check.synth import MUTATIONS, chassis_bom
    m = next(x for x in MUTATIONS if x.id == "ch_bom_typos")
    _, g0 = chassis
    g = _with_bom(g0, chassis_bom(m.params).encode())
    methods = {r["name"]: r["method"] for r in g.bom_rows}
    assert methods["Chasis Plate"] in ("exact", "fuzzy") and methods["Cover plate"] in ("exact", "fuzzy")
    assert methods["side-brackett"] == "fuzzy"
    assert {f.title for f in _doc(g)} == {"BOM row has no part in the CAD"}      # still only the two screw rows


def test_rows_naming_one_part_are_summed(chassis):
    _, g0 = chassis
    text = b"part_number,name,qty\nHW-010,standoff_M3x35,2\nHW-010,standoff_M3x35,2\nCH-001,chassis_plate,1\n" \
           b"CV-003,cover_plate,1\nBR-002,side_bracket,2\n"
    g = _with_bom(g0, text)
    assert [f for f in _doc(g) if f.title == "BOM quantity differs from the assembly"] == []


def test_export_lists_every_row_and_every_unmatched_part(chassis):
    out, g0 = chassis
    g = _with_bom(g0, b"part_number,name,qty\nCH-001,chassis_plate,1\nZZ-1,ghost,1\n")
    rows = export_rows(g)
    status = {(r["part_number"] or r["cad_part"]): r["status"] for r in rows}
    assert status["CH-001"] == "ok" and status["ZZ-1"] == "unmatched"
    assert status["side_bracket"] == "not in BOM" and status["standoff_M3x35"] == "not in BOM"


# --------------------------------------------------------------------- API --

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/r.sqlite")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("REVIEW_DEV_TOKEN", "t")
    monkeypatch.setenv("REVIEW_INLINE", "1")
    monkeypatch.setenv("REVIEW_AI", "off")
    import review.api as api
    monkeypatch.setattr(api, "_store", None)
    saved = dict(api.app.dependency_overrides)
    api.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(saved)


H = {"Authorization": "Bearer t"}


def test_bom_api_link_rechecks_and_export(client, chassis):
    out, _ = chassis
    p = client.post("/api/projects", json={"name": "Chassis"}, headers=H).json()
    bom = b"part_number,name,qty\nCH-001,chassis_plate,1\nCV-003,cover_plate,1\nBR-002,side_bracket,2\nXX-77,spacer post,4\n"
    rev = client.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": "A"},
                      files=[("files", ("chassis.step", out["step"].read_bytes())), ("files", ("bom.csv", bom))]).json()
    job = client.post(f"/api/revisions/{rev['id']}/run", headers=H).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert job["state"] == "done", job
    assert next(s for s in job["steps"] if s["key"] == "bom")["note"].startswith("4 rows")

    b = client.get(f"/api/revisions/{rev['id']}/bom", headers=H).json()
    row = next(r for r in b["rows"] if r["part_number"] == "XX-77")
    assert row["method"] == "none"
    titles = lambda: {(f["title"], f["status"]) for f in client.get(f"/api/revisions/{rev['id']}/findings", headers=H).json()["findings"]}
    assert ("CAD part has no BOM row", "open") in titles() and ("BOM row has no part in the CAD", "open") in titles()

    standoff = next(pp for pp in b["parts"] if pp["name"] == "standoff_M3x35")
    b2 = client.put(f"/api/revisions/{rev['id']}/bom/links", headers=H, json={"row_key": row["key"], "part_id": standoff["id"]}).json()
    linked = next(r for r in b2["rows"] if r["key"] == row["key"])
    assert linked["method"] == "human" and linked["part_id"] == standoff["id"]
    assert titles() == set()                    # both findings resolved by the pairing, checks re-run without geometry

    resolved = client.get(f"/api/revisions/{rev['id']}/findings?include_resolved=true", headers=H).json()["findings"]
    assert {f["status"] for f in resolved} == {"fixed"}

    client.request("DELETE", f"/api/revisions/{rev['id']}/bom/links", headers=H, json={"row_key": row["key"]})
    assert ("BOM row has no part in the CAD", "open") in titles()          # back to automatic matching, reopened

    csv_ = client.get(f"/api/revisions/{rev['id']}/bom.csv", headers=H)
    assert csv_.status_code == 200 and b"status" in csv_.content.splitlines()[0]
    xl = client.get(f"/api/revisions/{rev['id']}/bom.xlsx", headers=H)
    assert xl.status_code == 200 and xl.content[:2] == b"PK"


def test_flat_file_with_no_matches_says_so_once(chassis):
    out, g0 = chassis
    g = _with_bom(g0, b"part_number,name,qty\nZZ-1,ghost one,1\nZZ-2,ghost two,2\n")
    for p in g.parts:
        p.name = f"dump_body{p.id}"          # what a flattened export leaves
    g.stats.flat = True
    g = _with_bom(g, b"part_number,name,qty\nZZ-1,ghost one,1\nZZ-2,ghost two,2\n")
    found = _doc(g)
    assert [f.title for f in found] == ["BOM cannot be matched: the STEP has no part names"]
