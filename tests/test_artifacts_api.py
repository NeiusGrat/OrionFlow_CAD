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
