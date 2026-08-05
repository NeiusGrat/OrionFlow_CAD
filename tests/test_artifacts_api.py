"""The artifact download route, on both of the paths that reach it.

The legacy ``/api/v1/ofl/download/...`` shape is not a courtesy: it is written
into ``designs.glb_path`` and its siblings for every part any user has saved,
so a test that only covered the new path would let a refactor silently 404
every download link in production. Both are asserted here for that reason.

Uses a minimal app with only the artifact routers, to avoid pulling in
sqlalchemy/jose/redis through ``app.api.v1.__init__``.
"""

import importlib.util
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_spec = importlib.util.spec_from_file_location(
    "app.api.v1.artifacts",
    os.path.join(
        os.path.dirname(__file__), os.pardir, "app", "api", "v1", "artifacts.py"
    ),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.api.v1.artifacts"] = _mod
_spec.loader.exec_module(_mod)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(_mod.router, prefix="/api/v1/artifacts")
    app.include_router(_mod.legacy_router, prefix="/api/v1/ofl")
    return TestClient(app)


#: Every assertion below is made against both, deliberately.
PREFIXES = ("/api/v1/artifacts", "/api/v1/ofl/download")


@pytest.mark.parametrize("prefix", PREFIXES)
def test_missing_file_is_404(client, prefix):
    assert client.get(f"{prefix}/aabbccddeeff/nofile.step").status_code == 404


@pytest.mark.parametrize("prefix", PREFIXES)
def test_malformed_request_id_is_rejected(client, prefix):
    assert client.get(f"{prefix}/bad/file.step").status_code == 400


@pytest.mark.parametrize("prefix", PREFIXES)
def test_path_traversal_is_rejected(client, prefix):
    # Encoded slashes become extra path segments, so the route stops matching.
    encoded = client.get(f"{prefix}/aabbccddeeff/..%2F..%2Fetc%2Fpasswd")
    assert encoded.status_code in (400, 404)
    # A bare '..' reaches the handler and its own check has to catch it.
    assert client.get(f"{prefix}/aabbccddeeff/..passwd").status_code == 400


@pytest.mark.parametrize("prefix", PREFIXES)
def test_serves_a_real_artifact(client, tmp_path, monkeypatch, prefix):
    """A file that exists is served, whichever path asked for it."""
    request_id = "0123456789ab"
    directory = tmp_path / request_id
    directory.mkdir()
    (directory / "part.step").write_text("ISO-10303-21;")

    monkeypatch.setattr(_mod, "OUTPUT_BASE", str(tmp_path))

    response = client.get(f"{prefix}/{request_id}/part.step")
    assert response.status_code == 200
    assert response.text == "ISO-10303-21;"


@pytest.mark.parametrize("prefix", PREFIXES)
def test_serves_the_fcstd_as_a_binary_download(client, tmp_path, monkeypatch, prefix):
    """The FCStd is a zip; served as bytes, never guessed at as text.

    It reaches this route under both prefixes like everything else, but it is
    the one artifact a browser must not try to render or transcode — a mangled
    FCStd opens as a corrupt document rather than failing visibly.
    """
    request_id = "0123456789ab"
    directory = tmp_path / request_id
    directory.mkdir()
    (directory / "part.FCStd").write_bytes(b"PK\x03\x04\x00\x00document")

    monkeypatch.setattr(_mod, "OUTPUT_BASE", str(tmp_path))

    response = client.get(f"{prefix}/{request_id}/part.FCStd")
    assert response.status_code == 200
    assert response.content == b"PK\x03\x04\x00\x00document"
    assert response.headers["content-type"] == "application/octet-stream"


def _built(tmp_path, monkeypatch, content=b"ISO-10303-21;", manifest=True):
    """A request directory holding one artifact, with or without its manifest."""
    from app.services import artifacts as svc

    request_id = "0123456789ab"
    directory = tmp_path / request_id
    directory.mkdir()
    path = directory / "part.step"
    path.write_bytes(content)

    if manifest:
        entry = svc.file_digest(str(path))
        svc.write_manifest(
            str(directory), svc.new_manifest(request_id, {"step": entry})
        )

    monkeypatch.setattr(_mod, "OUTPUT_BASE", str(tmp_path))
    return request_id, directory


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_file_matching_its_manifest_is_served(client, tmp_path, monkeypatch, prefix):
    request_id, _ = _built(tmp_path, monkeypatch)
    response = client.get(f"{prefix}/{request_id}/part.step")
    assert response.status_code == 200
    assert response.content == b"ISO-10303-21;"


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_truncated_artifact_is_refused(client, tmp_path, monkeypatch, prefix):
    """The failure this guard exists for.

    A short write or a half-finished upload leaves a file that opens and renders
    as a part with missing geometry — indistinguishable, to the person looking
    at it, from a modelling mistake. Refusing it names the real problem.
    """
    request_id, directory = _built(tmp_path, monkeypatch)
    (directory / "part.step").write_bytes(b"ISO-103")  # same file, fewer bytes

    response = client.get(f"{prefix}/{request_id}/part.step")
    assert response.status_code == 409
    assert "recorded" in response.json()["detail"]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_an_artifact_without_a_manifest_is_still_served(
    client, tmp_path, monkeypatch, prefix
):
    """Every file built before manifests existed has none. Those links stay live."""
    request_id, _ = _built(tmp_path, monkeypatch, manifest=False)
    assert client.get(f"{prefix}/{request_id}/part.step").status_code == 200


def test_a_swapped_artifact_of_the_same_length_needs_verify(
    client, tmp_path, monkeypatch
):
    """Length alone cannot catch a same-size replacement; ``?verify=1`` can.

    Both behaviours are asserted together because the split between them is a
    deliberate cost decision, not an oversight: the viewer reloads a GLB far
    more often than anyone swaps a file for a different one of exactly equal
    size, so the hash is opt-in and its absence must not read as a bug.
    """
    request_id, directory = _built(tmp_path, monkeypatch)
    (directory / "part.step").write_bytes(b"ISO-99999999;")  # equal length

    assert client.get(f"/api/v1/artifacts/{request_id}/part.step").status_code == 200

    checked = client.get(f"/api/v1/artifacts/{request_id}/part.step?verify=1")
    assert checked.status_code == 409
    assert "sha256" in checked.json()["detail"]


def test_the_manifest_itself_is_downloadable(client, tmp_path, monkeypatch):
    """Provenance is useless if it cannot be read back off a finished build."""
    request_id, _ = _built(tmp_path, monkeypatch)

    response = client.get(f"/api/v1/artifacts/{request_id}/manifest.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    manifest = response.json()
    assert manifest["schema"] == "orionflow-artifact-v1"
    assert manifest["files"]["step"]["bytes"] == len(b"ISO-10303-21;")
    assert len(manifest["files"]["step"]["sha256"]) == 64


def test_both_paths_resolve_to_the_same_object_key():
    """Deleting a design has to reach the object behind either link shape."""
    from app.services.storage import storage_key_for

    assert (
        storage_key_for("/api/v1/ofl/download/aabbccddeeff/part.glb")
        == "ofl/aabbccddeeff/part.glb"
    )
    assert (
        storage_key_for("/api/v1/artifacts/aabbccddeeff/part.glb")
        == "ofl/aabbccddeeff/part.glb"
    )
