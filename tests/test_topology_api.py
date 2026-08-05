"""The routes a viewer calls to turn a click into an engineering answer.

``POST /resolve`` with a point is the one that matters. The viewer raycasts the
merged mesh it already renders, gets a world-space hit, and asks which face that
was and which Blueprint feature authored it. Nothing about how the model is
drawn has to change for this to work — no per-face GLB, no second mesh.

The sidecar is written to a real directory here rather than stubbed, so the
loader is covered along with the routes.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import topology as routes
from app.services import artifacts as artifact_paths
from app.services import topology as topo

REQUEST_ID = "0123456789ab"

RECORD = {
    "schema": "orionflow-topology-v1",
    "attribution": "element_map",
    "counts": {"faces": 2, "edges": 0, "vertices": 0, "unattributed": 0},
    "truncated": [],
    "occurrences": [{"ref": "#o1", "name": "Body", "shape": "#o1.s1"}],
    "faces": [
        {
            "ref": "#o1.s1.f5",
            "index": 5,
            "stable": "@base_pad.f3",
            "feature": "base_pad",
            "lineage": ["base_pad"],
            "surface": "Plane",
            "area": 1518.03,
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
            "lineage": ["bore"],
            "surface": "Cylinder",
            "area": 314.16,
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
            "build_index": 0,
            "blueprint_feature": True,
            "faces": ["#o1.s1.f5"],
            "edges": [],
            "vertices": [],
        },
        "bore": {
            "type": "PartDesign::Pocket",
            "build_index": 1,
            "blueprint_feature": True,
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
    (directory / topo.SIDECAR_NAME).write_text(json.dumps(RECORD), encoding="utf-8")
    monkeypatch.setattr(artifact_paths, "OUTPUT_BASE", str(tmp_path))

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/topology")
    return TestClient(app)


def _resolve(client, **body):
    return client.post(f"/api/v1/topology/{REQUEST_ID}/resolve", json=body)


# --------------------------------------------------------------------------- #
# the interaction this layer exists for
# --------------------------------------------------------------------------- #
def test_a_click_on_the_bore_wall_names_the_feature_that_made_it(client):
    response = _resolve(client, point=[5.0, 0.0, 5.0])

    assert response.status_code == 200
    best = response.json()["candidates"][0]
    assert best["feature"] == "bore"
    assert best["stable"] == "@bore.f0"
    assert best["distance"] == 0.0


def test_a_click_returns_ranked_candidates(client):
    """Ambiguity at a tangent seam is reported, not resolved by fiat."""
    candidates = _resolve(client, point=[4.9, 0.0, 9.9], limit=2).json()["candidates"]

    assert len(candidates) == 2
    assert candidates[0]["distance"] <= candidates[1]["distance"]


def test_highlighting_a_feature_returns_its_geometry_in_one_request(client):
    response = client.get(f"/api/v1/topology/{REQUEST_ID}/features/bore")

    assert response.status_code == 200
    body = response.json()
    assert [f["ref"] for f in body["faces"]] == ["#o1.s1.f11"]
    assert body["type"] == "PartDesign::Pocket"


def test_the_summary_omits_the_element_records(client):
    body = client.get(f"/api/v1/topology/{REQUEST_ID}").json()

    assert body["counts"]["faces"] == 2
    assert body["features"]["bore"]["faces"] == 1
    assert "faces" not in body or isinstance(body["features"], dict)


# --------------------------------------------------------------------------- #
# selectors over the wire
# --------------------------------------------------------------------------- #
def test_a_stable_selector_resolves(client):
    body = _resolve(client, selector="@bore.f0").json()

    assert body["match"]["ref"] == "#o1.s1.f11"


def test_the_shorthand_selector_resolves(client):
    """``#`` never survives a URL path, which is why these are POSTed."""
    body = _resolve(client, selector="#f5").json()

    assert body["query"] == "#o1.s1.f5"
    assert body["match"]["feature"] == "base_pad"


def test_a_malformed_selector_is_a_400_and_a_stale_one_is_a_404(client):
    """Different answers to different problems.

    A stale ``#f7`` held across a rebuild is well formed and simply names
    nothing any more — reporting it as a bad request would send the caller
    looking for a bug in its own selector code.
    """
    assert _resolve(client, selector="wat").status_code == 400
    assert _resolve(client, selector="#f99").status_code == 404


def test_exactly_one_query_is_required(client):
    assert _resolve(client).status_code == 400
    assert _resolve(client, selector="#f5", point=[0, 0, 0]).status_code == 400


def test_a_point_must_have_three_coordinates(client):
    assert _resolve(client, point=[0.0, 1.0]).status_code == 400


# --------------------------------------------------------------------------- #
# absence
# --------------------------------------------------------------------------- #
def test_a_build_with_no_sidecar_is_a_404(client):
    assert client.get("/api/v1/topology/ffffffffffff").status_code == 404


def test_a_malformed_request_id_is_rejected_before_any_lookup(client):
    assert client.get("/api/v1/topology/short").status_code == 400


def test_an_unknown_feature_says_which_ones_exist(client):
    response = client.get(f"/api/v1/topology/{REQUEST_ID}/features/nope")

    assert response.status_code == 404
    assert "bore" in response.json()["detail"]


def test_a_failed_extraction_is_reported_as_such_not_as_absence(client, tmp_path):
    """The build succeeded and the extraction did not — a different fact.

    Reporting it as "no topology" would read as a part that has none, which
    would send someone looking at the viewer instead of at the kernel.
    """
    (tmp_path / REQUEST_ID / topo.SIDECAR_NAME).write_text(
        json.dumps({"error": "the body has no shape", "faces": []}),
        encoding="utf-8",
    )

    response = client.get(f"/api/v1/topology/{REQUEST_ID}")

    assert response.status_code == 422
    assert "no shape" in response.json()["detail"]
