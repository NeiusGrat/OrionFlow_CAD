"""``/studio/edit`` — the click-to-rebuild round trip over HTTP.

Three routes, and the split between them is a cost decision the UI depends on:
``inspect`` and ``plan`` touch no kernel and are unmetered, so they can be called
on hover and on every frame of a slider drag; ``commit`` runs FreeCAD and is
metered exactly like ``/studio/rebuild``, because it is one.

Targeting by point is the case that matters. It is also the only one that needs
the topology sidecar, so the fixture writes a real one rather than stubbing the
resolver — the join between the two layers is the thing worth testing.

Built with a minimal app holding only the editing router, so the test does not
drag in auth/db/redis through ``app.api.v1.__init__``.
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import editing
from app.services import artifacts as artifact_paths
from app.services import blueprint_service
from app.services import studio_persistence as sp
from app.services import topology as topo

REQUEST_ID = "0123456789ab"

BLUEPRINT = {
    "part_class": "plate",
    "variables": {"t": 10.0, "w": 40.0, "hole_r": 5.0},
    "datums": {},
    "design_plan": {},
    "assertions": [],
    "template": {
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "base_pad", "type": "Pad", "parameters": {"Length": "t"}},
            {"id": "s1", "type": "Sketch", "parameters": {}},
            {"id": "bore", "type": "Pocket", "parameters": {"Length": "t"}},
        ],
        "sketches": [
            {
                "id": "s0",
                "plane": "XY",
                "profile": {"builder": "rect", "args": {"w": "w", "h": "w"}},
            },
            {
                "id": "s1",
                "plane": "XY",
                "profile": {"builder": "circle", "args": {"r": "hole_r"}},
            },
        ],
        "dependencies": [
            {"kind": "profile", "source": "s0", "target": "base_pad"},
            {"kind": "profile", "source": "s1", "target": "bore"},
        ],
    },
    "blueprint_hash": "abc",
}

#: The bore wall and the plate's top face, as FreeCAD records them.
TOPOLOGY = {
    "schema": "orionflow-topology-v1",
    "attribution": "element_map",
    "counts": {"faces": 2},
    "occurrences": [{"ref": "#o1", "name": "Body", "shape": "#o1.s1"}],
    "faces": [
        {
            "ref": "#o1.s1.f5",
            "index": 5,
            "stable": "@base_pad.f3",
            "feature": "base_pad",
            "surface": "Plane",
            "area": 1518.0,
            "center": [0.0, 0.0, 10.0],
            "normal": [0.0, 0.0, 1.0],
            "position": [0.0, 0.0, 10.0],
            "bbox": [-20.0, -20.0, 10.0, 20.0, 20.0, 10.0],
        },
        {
            "ref": "#o1.s1.f11",
            "index": 11,
            "stable": "@bore.f0",
            "feature": "bore",
            "surface": "Cylinder",
            "radius": 5.0,
            "axis": [0.0, 0.0, 1.0],
            "position": [0.0, 0.0, 10.0],
            "center": [0.0, 0.0, 5.0],
            "normal": [-1.0, 0.0, 0.0],
            "bbox": [-5.0, -5.0, 0.0, 5.0, 5.0, 10.0],
        },
    ],
    "edges": [],
    "vertices": [],
    "features": {
        "base_pad": {
            "type": "PartDesign::Pad",
            "faces": ["#o1.s1.f5"],
            "edges": [],
            "vertices": [],
        },
        "bore": {
            "type": "PartDesign::Pocket",
            "faces": ["#o1.s1.f11"],
            "edges": [],
            "vertices": [],
        },
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    directory = tmp_path / REQUEST_ID
    directory.mkdir()
    (directory / topo.SIDECAR_NAME).write_text(json.dumps(TOPOLOGY), encoding="utf-8")
    monkeypatch.setattr(artifact_paths, "OUTPUT_BASE", str(tmp_path))

    app = FastAPI()
    app.include_router(editing.router, prefix="/api/v1/studio/edit")
    state: dict = {"built": [], "recorded": []}

    def _build(payload, request_id=None):
        state["built"].append(payload)
        return {
            "success": True,
            "request_id": "ffffffffffff",
            "part_class": payload.get("part_class", ""),
            "variables": payload.get("variables", {}),
            "blueprint": payload,
            "files": {"step": "/api/v1/artifacts/ffffffffffff/part.step"},
            "topology": {"counts": {"faces": 2}},
            "stats": {"volume_mm3": 900.0},
            "verification": {"verdict": "verified", "checks": []},
            "measured": {"features": []},
            "build_log": {"where": "test", "build_report": {}},
            "generation_time_ms": 12.0,
            "error": None,
        }

    monkeypatch.setattr(blueprint_service, "build_from_payload", _build)

    async def _record(bundle, prompt, user_id):
        state["recorded"].append({"prompt": prompt, "user_id": user_id})

    monkeypatch.setattr(sp, "record_studio_build", _record)

    def _gate(verdict):
        app.dependency_overrides[editing.studio_gate] = lambda: verdict

    _gate(sp.StudioGate(user_id=uuid.uuid4(), allowed=True))
    return TestClient(app), state, _gate


def _post(client, route, **body):
    return client.post(f"/api/v1/studio/edit/{route}", json=body)


# --------------------------------------------------------------------------- #
# click -> feature -> dimensions
# --------------------------------------------------------------------------- #
def test_a_click_opens_the_panel_for_the_feature_that_made_the_face(client):
    """The round trip's first half, in one request."""
    tc, _, _ = client
    r = _post(
        tc,
        "inspect",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"point": [5.0, 0.0, 5.0]},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "bore"
    assert body["resolved"]["via"] == "point"
    assert body["resolved"]["element"]["stable"] == "@bore.f0"

    names = {p["name"]: p for p in body["parameters"]}
    assert names["profile.r"]["value"] == 5.0
    assert names["profile.r"]["variable"] == "hole_r"
    assert names["Length"]["shared_with"] == ["base_pad.Length"]


def test_a_selector_and_a_feature_id_reach_the_same_place(client):
    tc, _, _ = client
    by_selector = _post(
        tc,
        "inspect",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"selector": "@bore.f0"},
    ).json()
    by_id = _post(tc, "inspect", blueprint=BLUEPRINT, target={"feature": "bore"}).json()

    assert by_selector["feature"] == by_id["feature"] == "bore"
    assert by_selector["parameters"] == by_id["parameters"]
    # A feature id needs no build; it is the identity that outlives the artifact.
    assert by_id["resolved"] == {"via": "feature"}


def test_an_ambiguous_click_carries_its_runners_up(client):
    """A pick is a ranked guess against a mesh, and says so.

    A UI holding the alternatives can offer "did you mean the top face?"; one
    given a single answer has to pretend the inference was a measurement.
    """
    tc, _, _ = client
    body = _post(
        tc,
        "inspect",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"point": [4.9, 0.0, 9.9]},
    ).json()

    assert body["resolved"]["other_candidates"]


# --------------------------------------------------------------------------- #
# planning costs nothing
# --------------------------------------------------------------------------- #
def test_planning_reports_what_moves_and_builds_nothing(client):
    tc, state, _ = client
    r = _post(
        tc,
        "plan",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"point": [5.0, 0.0, 5.0]},
        parameter="profile.r",
        value=7.0,
    )

    assert r.status_code == 200
    plan = r.json()["plan"]
    assert (plan["variable"], plan["before"], plan["after"]) == ("hole_r", 5.0, 7.0)
    assert plan["contract_preserved"] is True
    assert state["built"] == []


def test_planning_a_shared_dimension_shows_the_linkage(client):
    tc, _, _ = client
    plan = _post(
        tc,
        "plan",
        blueprint=BLUEPRINT,
        target={"feature": "base_pad"},
        parameter="Length",
        value=14.0,
    ).json()["plan"]

    assert plan["variable"] == "t"
    assert [m["path"] for m in plan["also_moves"]] == ["bore.Length"]


def test_planning_is_not_gated(client):
    """No kernel, no meter — the UI calls this on every drag."""
    tc, _, gate = client
    gate(sp.StudioGate(user_id=None, allowed=False))

    r = _post(
        tc,
        "plan",
        blueprint=BLUEPRINT,
        target={"feature": "bore"},
        parameter="profile.r",
        value=7.0,
    )

    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# committing rebuilds
# --------------------------------------------------------------------------- #
def test_committing_rebuilds_with_the_new_value(client):
    tc, state, _ = client
    r = _post(
        tc,
        "commit",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"point": [5.0, 0.0, 5.0]},
        parameter="profile.r",
        value=7.0,
    )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert state["built"][0]["variables"]["hole_r"] == 7.0
    # Only the value moved: the template is untouched, so the verdict grades
    # this geometry against the contract it was designed to.
    assert body["contract_broken"] is False
    assert body["verification"]["verdict"] == "verified"


def test_the_commit_response_carries_the_plan_beside_the_result(client):
    """ "What I asked for" and "what came out" are different claims."""
    tc, _, _ = client
    body = _post(
        tc,
        "commit",
        blueprint=BLUEPRINT,
        target={"feature": "bore"},
        parameter="profile.r",
        value=7.0,
    ).json()

    assert body["plan"]["before"] == 5.0
    assert body["plan"]["after"] == 7.0
    assert body["variables"]["hole_r"] == 7.0


def test_committing_is_metered_like_any_other_build(client):
    tc, state, _ = client
    _post(
        tc,
        "commit",
        blueprint=BLUEPRINT,
        target={"feature": "bore"},
        parameter="profile.r",
        value=7.0,
    )

    assert state["recorded"]
    assert "bore.profile.r" in state["recorded"][0]["prompt"]


@pytest.mark.parametrize(
    "verdict,expected",
    [
        # Anonymous: `known` is derived from user_id, so no account is no id.
        (dict(user_id=None, allowed=False), 401),
        (dict(user_id=uuid.uuid4(), allowed=False, reason="limit"), 429),
    ],
)
def test_committing_needs_a_signed_in_caller_within_quota(client, verdict, expected):
    tc, _, gate = client
    gate(sp.StudioGate(**verdict))

    r = _post(
        tc,
        "commit",
        blueprint=BLUEPRINT,
        target={"feature": "bore"},
        parameter="profile.r",
        value=7.0,
    )

    assert r.status_code == expected


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #
def test_a_computed_dimension_is_refused_before_the_kernel(client):
    """A 400, not a failed build — the distinction matters to the panel."""
    tc, state, _ = client
    edited = json.loads(json.dumps(BLUEPRINT))
    edited["template"]["features"][4]["parameters"]["Length"] = "t * 2"

    r = _post(
        tc,
        "commit",
        blueprint=edited,
        target={"feature": "bore"},
        parameter="Length",
        value=14.0,
    )

    assert r.status_code == 400
    assert "edit t instead" in r.json()["detail"]["error"]
    assert state["built"] == []


def test_exactly_one_way_of_pointing_is_required(client):
    tc, _, _ = client
    assert _post(tc, "inspect", blueprint=BLUEPRINT, target={}).status_code == 400
    assert (
        _post(
            tc,
            "inspect",
            blueprint=BLUEPRINT,
            request_id=REQUEST_ID,
            target={"feature": "bore", "point": [0, 0, 0]},
        ).status_code
        == 400
    )


def test_pointing_at_geometry_needs_the_build_it_belongs_to(client):
    """A selector is an address in one artifact; without it there is nothing
    to resolve against."""
    tc, _, _ = client
    r = _post(tc, "inspect", blueprint=BLUEPRINT, target={"selector": "#f11"})

    assert r.status_code == 400
    assert "request_id" in r.json()["detail"]


def test_a_stale_selector_is_a_404_not_a_bad_request(client):
    tc, _, _ = client
    r = _post(
        tc,
        "inspect",
        blueprint=BLUEPRINT,
        request_id=REQUEST_ID,
        target={"selector": "#f99"},
    )

    assert r.status_code == 404


def test_a_build_with_no_topology_cannot_be_clicked(client):
    tc, _, _ = client
    r = _post(
        tc,
        "inspect",
        blueprint=BLUEPRINT,
        request_id="ffffffffffff",
        target={"point": [0.0, 0.0, 0.0]},
    )

    assert r.status_code == 404
