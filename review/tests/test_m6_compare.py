"""M6: revision compare — part matching, change list, interchangeability, findings delta."""
from __future__ import annotations

import pytest

from review.checks import run_checks
from review.compare import compare, findings_delta, match_parts
from review.ingest import build_graph


def _graph(tmp_path, assembly, params, stem):
    from interface_check.synth import build
    out = build(assembly, params, tmp_path / stem, stem=stem)
    return build_graph(out["step"], stem)


def _f(graph):
    findings, _ = run_checks(graph)
    return [{"check_id": f.check_id, "title": f.title, "evidence": [e.model_dump(exclude_none=True) for e in f.evidence]}
            for f in findings]


def test_identical_revisions_change_nothing(tmp_path):
    a = _graph(tmp_path, "chassis", {}, "a")
    b = _graph(tmp_path, "chassis", {}, "b")
    r = compare(a, b)
    assert r["summary"]["modified"] == r["summary"]["added"] == r["summary"]["removed"] == 0
    assert {m["verdict"] for m in r["interchangeability"]} == {"yes"}


@pytest.mark.parametrize("mid", ["rev_plate_holes", "rev_base_pcd"])
def test_revision_mutations(tmp_path, mid):
    from interface_check.synth import MUTATIONS
    m = next(x for x in MUTATIONS if x.id == mid)
    base = _graph(tmp_path, m.assembly, m.prev, "base")
    target = _graph(tmp_path, m.assembly, m.params, "target")
    r = compare(base, target)
    changed = {c["target_name"] for c in r["changes"] if c["status"] == "modified"}
    assert changed == set(m.expect_change), r["changes"]
    verdict = {x["name"]: x for x in r["interchangeability"]}
    for name in m.expect_change:
        assert verdict[name]["verdict"] in ("no", "needs review"), verdict[name]
    others = {x["name"] for x in r["interchangeability"] if x["verdict"] == "yes"}
    assert others == {p.name for p in target.parts} - set(m.expect_change)
    # the error the change introduced is a new finding
    delta = findings_delta(_f(base), _f(target), base, target, r["pairs"])
    new = {f["check_id"] for f in delta["new"]}
    assert ({"IF-HOLE-ALIGN"} if mid == "rev_plate_holes" else {"IF-PATTERN"}) <= new
    assert not delta["fixed"]


def test_bolt_circle_change_is_not_interchangeable(tmp_path):
    base = _graph(tmp_path, "bearing_joint", {}, "base")
    target = _graph(tmp_path, "bearing_joint", {"base_pcd": 43.0}, "target")
    r = compare(base, target)
    (v,) = [x for x in r["interchangeability"] if x["name"] == "base"]
    assert v["verdict"] == "no" and "bolt pattern" in v["reason"]


def test_renamed_part_is_matched_by_signature(tmp_path):
    from build123d import Box, Compound, Pos, export_step

    def asm(name_b, path, qty=2):
        a = Pos(0, 0, 5) * Box(40, 40, 10)
        a.label = "base_plate"
        kids = [a]
        for k in range(qty):
            b = Pos(-10 + 20 * k, 0, 13) * Box(8, 8, 6)
            b.label = name_b
            kids.append(b)
        c = Compound(children=kids)
        c.label = "asm"
        export_step(c, str(path).replace("\\", "/"))
        return build_graph(path, path.stem)

    g1 = asm("spacer", tmp_path / "r1.step")
    g2 = asm("SPC-0042", tmp_path / "r2.step", qty=3)
    pairs = match_parts(g1, g2)
    by_name = {(next((p.name for p in g1.parts if p.id == pr["base"]), None),
                next((p.name for p in g2.parts if p.id == pr["target"]), None)): pr["method"] for pr in pairs}
    assert by_name[("spacer", "SPC-0042")] == "signature"
    r = compare(g1, g2)
    spacer = next(c for c in r["changes"] if c["target_name"] == "SPC-0042")
    assert "quantity" in spacer["kinds"] and "renamed" in spacer["kinds"] and "quantity 2 → 3" in spacer["details"]
    assert next(m for m in r["interchangeability"] if m["name"] == "SPC-0042")["verdict"] == "yes"   # same geometry


def test_added_and_removed(tmp_path):
    from build123d import Box, Compound, Pos, export_step

    def asm(extra, path):
        a = Pos(0, 0, 5) * Box(40, 40, 10)
        a.label = "base_plate"
        kids = [a]
        if extra:
            e = Pos(0, 0, 13) * Box(*extra)
            e.label = "cover" if extra[0] > 10 else "tab"
            kids.append(e)
        c = Compound(children=kids)
        c.label = "asm"
        export_step(c, str(path).replace("\\", "/"))
        return build_graph(path, path.stem)

    r = compare(asm((5, 5, 6), tmp_path / "a.step"), asm((30, 30, 6), tmp_path / "b.step"))
    status = {(c["base_name"], c["target_name"]): c["status"] for c in r["changes"]}
    assert status[("tab", None)] == "removed" and status[(None, "cover")] == "added"


def test_api_compare(tmp_path, monkeypatch):
    from interface_check.synth import build
    monkeypatch.setenv("REVIEW_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/r.sqlite")
    monkeypatch.setenv("REVIEW_STORAGE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("REVIEW_DEV_TOKEN", "t")
    monkeypatch.setenv("REVIEW_INLINE", "1")
    import review.api as api
    monkeypatch.setattr(api, "_store", None)
    saved = dict(api.app.dependency_overrides)
    api.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    H = {"Authorization": "Bearer t"}
    try:
        p = c.post("/api/projects", json={"name": "MM"}, headers=H).json()
        revs = []
        for label, params in (("A", {}), ("B", {"corner_shift": (0, 1.0)})):
            step = build("motor_mount", params, tmp_path / label)["step"]
            rev = c.post(f"/api/projects/{p['id']}/revisions", headers=H, data={"label": label},
                         files=[("files", ("mm.step", step.read_bytes()))]).json()
            c.post(f"/api/revisions/{rev['id']}/run", headers=H)
            revs.append(rev["id"])
        r = c.post(f"/api/revisions/{revs[0]}/compare/{revs[1]}", headers=H).json()
        assert r["summary"]["modified"] == 1 and r["summary"]["new_findings"] >= 1
        assert r["base"]["label"] == "A" and r["target"]["label"] == "B"
        assert [f["check_id"] for f in r["findings"]["new"]] == ["IF-HOLE-ALIGN"]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(saved)
