"""Tests for the artifact storage layer (app/services/storage.py)."""

from app.config import settings
from app.services.storage import LocalStorage, get_storage, publish_artifacts


def setup_function():
    get_storage.cache_clear()


def teardown_function():
    get_storage.cache_clear()


def test_local_storage_selected_when_s3_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", None)
    assert isinstance(get_storage(), LocalStorage)


def test_local_publish_returns_outputs_url(tmp_path):
    f = tmp_path / "abc.glb"
    f.write_bytes(b"x")
    assert LocalStorage().publish(f) == "outputs/abc.glb"


def test_local_url_for_missing_file_is_none():
    assert LocalStorage().url_for("does-not-exist.step") is None


def test_publish_artifacts_skips_missing_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", None)
    get_storage.cache_clear()
    real = tmp_path / "part.step"
    real.write_bytes(b"solid")
    urls = publish_artifacts(real, tmp_path / "ghost.stl", None)
    assert urls == {"step": "outputs/part.step"}
