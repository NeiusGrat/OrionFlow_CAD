"""Engine-side protections: complexity gate, mesh bodies, part cache, contact caps, grounded narrative."""
import warnings

import pytest

from interface_check.cache import FeatureCache, geometry_hash
from interface_check.errors import AnalysisError
from interface_check.features import classify_body
from interface_check.ingest_step import read_assembly
from interface_check.inspect_step import inspect
from interface_check.interfaces import contact_planes
from interface_check.limits import limits_for
from interface_check.llm import LLM, narrate
from interface_check.pipeline import gate, run_check
from interface_check.synth import build, mesh_body

warnings.filterwarnings("ignore", module="build123d")


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("scale")
    return {"motor": build("motor_mount", {}, d / "m"), "mesh": build("mesh_bracket", {"base_tap": 3.3}, d / "x"),
            "dir": d}


def test_gate_counts_without_building_geometry(files):
    c = inspect(files["motor"]["step"])
    assert c.valid_header and c.terminated and c.solid_count == 3 and c.face_count == 51
    assert c.mesh_ratio == 0 and c.tier == "SMALL"
    m = inspect(files["mesh"]["step"])
    assert m.mesh_ratio > 0.9 and m.triangle_loops > 800


def test_gate_refuses_by_plan_limits(files, monkeypatch):
    monkeypatch.setenv("IC_LIMIT_FREE_MAX_FACES", "40")
    with pytest.raises(AnalysisError) as e:
        gate(files["motor"]["step"], limits_for("free"))
    assert e.value.code == "TOO_MANY_FACES" and e.value.retry == "never"


def test_gate_rejects_non_step(tmp_path):
    p = tmp_path / "x.step"
    p.write_text("solid ascii stl\nendsolid\n")
    with pytest.raises(AnalysisError) as e:
        gate(p, limits_for("free"))
    assert e.value.code == "INVALID_STEP"


def test_mesh_body_is_classified_and_skipped(files):
    from build123d import Box
    assert classify_body(Box(10, 10, 10).wrapped)[0] == "BREP"
    r = run_check(files["mesh"]["step"]).to_dict()
    types = {p["part"]: p["geometry_type"] for p in r["parts"]}
    assert types == {"top_plate": "BREP", "base_block": "BREP", "scanned_cover": "MESH"}
    rules = {f["rule_id"] for f in r["findings"]}
    assert "UNSUPPORTED_GEOMETRY" in rules and "FASTENER_SIZE_MISMATCH" in rules   # B-rep joint still checked
    mesh_pairs = [i for i in r["interfaces"] if "scanned_cover" in i["a"] + i["b"]]
    assert mesh_pairs and all(not i["exact"] for i in mesh_pairs)                  # adjacency only, no extrema


def test_all_mesh_assembly_is_unsupported(tmp_path):
    from build123d import Compound, Sphere, export_step
    body = mesh_body(Sphere(10), 0.5)
    body.label = "scan"
    asm = Compound(children=[body])
    asm.label = "scan_only"
    p = tmp_path / "scan.step"
    export_step(asm, str(p).replace("\\", "/"))
    with pytest.raises(AnalysisError) as e:
        run_check(p)
    assert e.value.code == "UNSUPPORTED_MESH"


def test_geometry_hash_is_stable_across_reads(files):
    a, _, _ = read_assembly(files["motor"]["step"])
    b, _, _ = read_assembly(files["motor"]["step"])
    ha = sorted(geometry_hash(p.shape) for p in a.values())
    hb = sorted(geometry_hash(p.shape) for p in b.values())
    assert ha == hb and len(set(ha)) == 3


def test_cache_hits_unchanged_parts_of_a_new_revision(files, tmp_path):
    cache = FeatureCache(tmp_path / "cache")
    run_check(files["motor"]["step"], cache=cache)
    rev_c = build("motor_mount", {"corner_shift": (0, 1.0)}, tmp_path / "revc")
    r = run_check(rev_c["step"], cache=cache).to_dict()
    assert r["stats"]["cache"] == {"hits": 2, "misses": 1, "hit_rate": 0.6667}   # only the plate changed
    assert "HOLE_MISALIGNED" in {f["rule_id"] for f in r["findings"]}          # cached features still check


def test_contact_candidates_are_capped(files):
    from interface_check.pipeline import analyse
    a = analyse(files["motor"]["step"])
    plate = next(i for i in a.instances if "plate" in i.path)
    frame = next(i for i in a.instances if "frame" in i.path)
    stats: dict = {}
    pairs = contact_planes(a.feats[plate.instance_id], a.feats[frame.instance_id], max_pairs=0, stats=stats)
    assert pairs == [] and stats["candidates"] >= 1 and stats["capped"] == stats["candidates"]


class _FakeLLM(LLM):
    name = "fake"

    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def json(self, task, prompt, schema, images=()):
        return self.answer


def test_narrative_drops_uncited_and_invented_numbers(files):
    r = run_check(build("bearing_joint", {"housing_bore": 22.5}, files["dir"] / "b")["step"]).to_dict()
    fp = r["findings"][0]["fingerprint"]
    llm = _FakeLLM({"summary": "One bearing seat problem.", "points": [
        {"text": "Housing bore is 22.5 mm against a 22 mm bearing.", "cites": [fp]},       # grounded
        {"text": "The bore is 23.7 mm oversize.", "cites": [fp]},                         # invented number
        {"text": "Bolts are loose.", "cites": ["nonexistent"]},                           # cites nothing real
    ]})
    n = narrate(llm, r)
    assert n["status"] == "llm" and [p["text"] for p in n["points"]] == [
        "Housing bore is 22.5 mm against a 22 mm bearing."] and n["dropped"] == 2


def test_stages_cover_the_whole_pipeline(files):
    r = run_check(files["motor"]["step"]).to_dict()
    assert [s["stage_id"] for s in r["stages"]] == [f"{i:02d}" for i in range(1, 16)]
    by = {s["stage"]: s for s in r["stages"]}
    assert by["gdt_dimensions"]["status"] == "SKIPPED" and by["final_report"]["status"] == "PASS"
    assert all(c["engine_version"] for c in r["checks"])


def test_narrative_never_blocks_on_a_failing_model(files):
    class Broken(_FakeLLM):
        def json(self, task, prompt, schema, images=()):
            raise TimeoutError("model did not answer")
    r = run_check(build("bearing_joint", {"housing_bore": 22.5}, files["dir"] / "slow")["step"]).to_dict()
    n = narrate(Broken({}), r)
    assert n["status"] == "fallback" and "TimeoutError" in n["reason"] and n["summary"]
