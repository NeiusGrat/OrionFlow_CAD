"""Integration tests for OFL API endpoints.

Uses a minimal FastAPI app with only the OFL router to avoid
pulling in sqlalchemy/redis/etc dependencies.
"""

import os
import sys
import importlib
import importlib.util
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import ofl.py directly to bypass app.api.v1.__init__.py (which imports
# auth/users/etc that require sqlalchemy/jose/etc).
_ofl_spec = importlib.util.spec_from_file_location(
    "app.api.v1.ofl",
    os.path.join(os.path.dirname(__file__), os.pardir, "app", "api", "v1", "ofl.py"),
)
_ofl_mod = importlib.util.module_from_spec(_ofl_spec)
sys.modules["app.api.v1.ofl"] = _ofl_mod
_ofl_spec.loader.exec_module(_ofl_mod)
ofl_router = _ofl_mod.router


def _make_app():
    app = FastAPI()
    app.include_router(ofl_router, prefix="/api/v1/ofl")
    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


def test_rebuild_endpoint(client):
    """Test rebuild with known-good OFL code (no LLM needed)."""
    response = client.post("/api/v1/ofl/rebuild", json={
        "ofl_code": (
            'from orionflow_ofl import *\n'
            'part = Sketch(Plane.XY).rect(50, 50).extrude(5)\n'
            'export(part, "test.step")'
        )
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["files"]["step"] is not None
    assert data["ofl_code"].startswith("from orionflow_ofl")


def test_rebuild_bad_code(client):
    """Test rebuild with invalid OFL code returns error, not crash."""
    response = client.post("/api/v1/ofl/rebuild", json={
        "ofl_code": (
            'from orionflow_ofl import *\n'
            'part = Sketch(Plane.XY).rect("bad", 50).extrude(5)\n'
            'export(part, "test.step")'
        )
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["error"] is not None


def test_rebuild_blocks_dangerous_code(client):
    """Ensure sandbox blocks dangerous code via API."""
    response = client.post("/api/v1/ofl/rebuild", json={
        "ofl_code": "import os; os.system('echo pwned')"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Blocked" in data["error"]


def test_download_nonexistent_file(client):
    """Download of nonexistent file returns 404."""
    response = client.get("/api/v1/ofl/download/aabbccddeeff/nofile.step")
    assert response.status_code == 404


def test_download_invalid_request_id(client):
    """Download with invalid request_id returns 400."""
    response = client.get("/api/v1/ofl/download/bad/file.step")
    assert response.status_code == 400


def test_download_path_traversal(client):
    """Download blocks path traversal."""
    # URL-encoded slashes become extra path segments → 404 (route mismatch)
    response = client.get("/api/v1/ofl/download/aabbccddeeff/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)
    # Direct '..' in filename → 400 (our validation catches it)
    response2 = client.get("/api/v1/ofl/download/aabbccddeeff/..passwd")
    assert response2.status_code == 400
