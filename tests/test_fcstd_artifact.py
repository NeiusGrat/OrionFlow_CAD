"""The FCStd survives the whole way out, at every seam that used to drop it.

``orion/build_export_fc.py`` has always saved a ``part.FCStd`` — it is the first
thing it does, before any export — but nothing carried it further. The Modal
builder read back only ``part.step`` and ``part.stl``, so on the cloud path (the
one every studio user hits) the document died with the container, and there was
nowhere on ``designs`` to record it even when it survived. Every part this
system built lost its feature history at that boundary, and the loss was silent
because a STEP still arrived and still rendered.

That is the failure this file exists to prevent recurring. STEP and STL are the
finished solid; the FCStd is the sketches, the feature tree and the expressions
binding dimensions to named variables — the difference between a part that can
be reopened and retuned and one that can only be looked at.

Four seams, one test each, because losing it at any of them looks identical to
the user:

1. the builder container returning it,
2. the API writing it into the request's workdir,
3. the bundle advertising it as a download,
4. the build record remembering where it went.
"""

import ast
import os
import sys
import types

import pytest

from app.services import blueprint_service as bs
from app.services import studio_persistence as sp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def plate():
    """A minimal Blueprint that freezes and resolves: one sketch, one pad."""
    return {
        "part_class": "plate",
        "variables": {"thick": 6.0, "width": 40.0},
        "datums": {},
        "design_plan": {},
        "assertions": [],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad", "parameters": {"Length": "thick"}},
            ],
            "sketches": [
                {
                    "id": "s0",
                    "plane": "XY",
                    "profile": {
                        "builder": "rect",
                        "args": {"w": "width", "h": "width"},
                    },
                }
            ],
            "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"}],
        },
    }


# --------------------------------------------------------------------------- #
# 1. the container
# --------------------------------------------------------------------------- #
def test_the_modal_builder_returns_the_fcstd():
    """``build_blueprint`` must read part.FCStd back out of its workdir.

    Asserted against the source rather than by calling it, because
    ``deploy/modal_builder.py`` cannot be imported without the ``modal``
    package, which is a deploy-time dependency and deliberately not in the test
    environment. The property is still worth pinning: this exact line is the one
    whose absence discarded every FCStd the system ever built, and its absence
    is invisible from the API side — the build still succeeds and a STEP still
    comes back.
    """
    source = open(
        os.path.join(REPO_ROOT, "deploy", "modal_builder.py"), encoding="utf-8"
    ).read()
    tree = ast.parse(source)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_blueprint"
    )
    literals = {
        n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "part.FCStd" in literals, (
        "build_blueprint no longer names part.FCStd — the parametric document "
        "is being discarded with the container again"
    )


# --------------------------------------------------------------------------- #
# 2. the workdir
# --------------------------------------------------------------------------- #
def test_modal_artifacts_are_written_into_the_workdir(tmp_path, monkeypatch):
    """Whatever the builder returns lands on disk under the request id.

    The FCStd is returned as bytes like the rest, so the only thing that can go
    wrong here is the caller filtering the dict — which is why the assertion is
    on the file existing, not on the return value.
    """

    class _Function:
        @staticmethod
        def from_name(_app, _fn):
            class _Handle:
                @staticmethod
                def remote(_graph, _mesh):
                    return {
                        "build_log": {"returncode": 0},
                        "measured": {"body_volume": 9600.0},
                        "artifacts": {
                            "part.step": b"ISO-10303-21;",
                            "part.stl": b"solid\nendsolid\n",
                            "part.FCStd": b"PK\x03\x04fake-freecad-document",
                        },
                    }

            return _Handle

    fake_modal = types.ModuleType("modal")
    fake_modal.Function = _Function
    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    log, measured = bs._build_on_modal({}, str(tmp_path))

    assert log["where"] == "modal"
    assert measured == {"body_volume": 9600.0}
    written = (tmp_path / "part.FCStd").read_bytes()
    assert written == b"PK\x03\x04fake-freecad-document"


# --------------------------------------------------------------------------- #
# 3. the bundle
# --------------------------------------------------------------------------- #
def _stub_build(monkeypatch, tmp_path, produce):
    """Point the service at ``tmp_path`` and have the builder write ``produce``.

    ``produce`` maps filename -> contents, so a test can describe a build that
    saved its document but failed to export, or the other way round.
    """
    from app.services import artifacts

    monkeypatch.setattr(artifacts, "workdir", lambda _rid: str(tmp_path))

    def _fake_builder(_graph, workdir, mesh_body=False):
        for name, body in produce.items():
            with open(os.path.join(workdir, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        return {"returncode": 0, "where": "test"}, {
            "body_volume": 9600.0,
            "bbox": [0, 0, 0, 40, 40, 6],
            "watertight": True,
        }

    monkeypatch.setattr(bs, "run_builder", _fake_builder)


def test_the_bundle_advertises_the_fcstd(plate, tmp_path, monkeypatch):
    _stub_build(
        monkeypatch,
        tmp_path,
        {"part.FCStd": "document", "part.step": "ISO-10303-21;", "part.stl": "solid"},
    )

    bundle = bs.build_from_payload(plate, request_id="0123456789ab")

    assert bundle["success"] is True
    assert bundle["files"]["fcstd"].endswith("/0123456789ab/part.FCStd")


def test_an_fcstd_alone_is_not_a_successful_build(plate, tmp_path, monkeypatch):
    """A document with no exports is not something the user can see or use.

    Worth pinning because ``success`` was previously ``bool(files)``: adding the
    FCStd to that dict would have started reporting success for builds with no
    STEP, no STL and therefore no GLB — an empty viewer described as a finished
    part.
    """
    _stub_build(monkeypatch, tmp_path, {"part.FCStd": "document"})

    bundle = bs.build_from_payload(plate, request_id="0123456789ab")

    assert bundle["files"]["fcstd"]
    assert bundle["success"] is False
    assert bundle["error"] == "the build produced no measurable solid"


# --------------------------------------------------------------------------- #
# 4. the record
# --------------------------------------------------------------------------- #
def test_build_evidence_remembers_where_the_artifacts_went():
    """Recorded for every build, not only the ones a user chooses to save.

    ``designs.fcstd_path`` covers the saved case. This covers the rest — the
    builds that were tried, judged and moved on from, which are the ones a
    corpus of real design sessions is actually made of.
    """
    evidence = sp.build_evidence(
        {
            "files": {"fcstd": "/api/v1/artifacts/0123456789ab/part.FCStd"},
            "blueprint": {"blueprint_hash": "abc123", "part_class": "plate"},
            "measured": {"features": []},
        }
    )

    assert evidence["artifacts"]["fcstd"].endswith("part.FCStd")
    assert evidence["blueprint_hash"] == "abc123"


def test_build_evidence_survives_a_build_that_produced_nothing():
    """A failed turn still writes a record; it must not raise on the way."""
    evidence = sp.build_evidence({})

    assert evidence["artifacts"] == {}
    assert evidence["blueprint_hash"] == ""
