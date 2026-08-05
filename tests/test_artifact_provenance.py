"""What a build records about itself, and where that record lives.

Three facts about every built file were unrecoverable after the fact:

* **what the file was** — ``artifacts`` held URLs and nothing else, so a file
  that arrived truncated, or a directory rebuilt under a request id an old link
  still pointed at, was undetectable. A short GLB reaches the viewer as a part
  with missing faces, which reads as a modelling failure rather than a broken
  download.
* **which build of the service wrote it** — a deploy has already once served
  stale code while reporting success, and nothing about the geometry reveals
  that. The only evidence is the build stamp, recorded at write time or never.
* **which kernel compiled it** — ``design_revisions.freecad_version`` has
  existed since the table was created and nothing ever wrote it. The corpus was
  verified under FreeCAD 1.1; an image that ships something else produces
  geometry disagreeing with frozen predictions for no visible reason.

All three are stamped in ``blueprint_service._finish``, the single point both
the synchronous and asynchronous builders converge on — the same reason that
function exists at all.
"""

import json
import os

import pytest

from app.services import artifacts
from app.services import blueprint_service as bs
from app.services import studio_persistence as sp


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
        },
    }


@pytest.fixture
def built(monkeypatch, tmp_path):
    """Run a build in ``tmp_path`` with a stubbed kernel.

    Returns a callable taking the files to produce and what the builder reports,
    so each test states the build it means rather than sharing one.
    """
    monkeypatch.setattr(artifacts, "workdir", lambda _rid: str(tmp_path))

    def _run(payload, produce, measured=None, returncode=0):
        def _builder(_graph, workdir, mesh_body=False):
            for name, body in produce.items():
                with open(os.path.join(workdir, name), "w", encoding="utf-8") as fh:
                    fh.write(body)
            if returncode != 0:
                return {
                    "returncode": returncode,
                    "stderr": "boom",
                    "where": "test",
                }, None
            return {"returncode": 0, "where": "test"}, {
                "body_volume": 9600.0,
                "bbox": [0, 0, 0, 40, 40, 6],
                "watertight": True,
                **(measured or {}),
            }

        monkeypatch.setattr(bs, "run_builder", _builder)
        return bs.build_from_payload(payload, request_id="0123456789ab")

    return _run


# --------------------------------------------------------------------------- #
# the digest
# --------------------------------------------------------------------------- #
def test_every_built_file_is_digested(plate, built):
    """A URL says where a file went; only a digest says what it was."""
    bundle = built(
        plate,
        {"part.FCStd": "document", "part.step": "ISO-10303-21;", "part.stl": "solid"},
    )

    for kind in ("fcstd", "step", "stl"):
        assert set(bundle["artifact_digests"][kind]) == {"name", "bytes", "sha256"}
        assert len(bundle["artifact_digests"][kind]["sha256"]) == 64
    assert bundle["artifact_digests"]["step"]["bytes"] == len("ISO-10303-21;")


def test_the_digest_describes_the_bytes_that_landed(plate, built, tmp_path):
    """Hashed here, not in the kernel worker, and that is the whole point.

    On the Modal path the artifacts cross a container boundary as bytes and are
    rewritten locally. A hash taken before that trip would attest to a file that
    is no longer the one being served, and would agree with itself while the
    transfer silently truncated.
    """
    bundle = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})

    on_disk = artifacts.file_digest(str(tmp_path / "part.step"))
    assert bundle["artifact_digests"]["step"] == on_disk


def test_a_digest_of_an_unreadable_file_is_not_an_error():
    """Evidence about an artifact is not the artifact.

    Failing to compute one must never turn a successful build into a failed one.
    """
    assert artifacts.file_digest("no/such/file.step") is None


# --------------------------------------------------------------------------- #
# the manifest
# --------------------------------------------------------------------------- #
def test_the_manifest_lands_beside_the_artifacts(plate, built, tmp_path):
    """Written into the build directory, not only returned to the caller.

    The bundle is transient and the database row is somewhere else entirely; the
    download route consults neither. Putting the record in the directory it
    describes is what lets a file be checked against it later.
    """
    bundle = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema"] == artifacts.MANIFEST_SCHEMA
    assert manifest["request_id"] == "0123456789ab"
    assert manifest["built_where"] == "test"
    assert manifest["files"]["step"] == bundle["artifact_digests"]["step"]
    assert manifest["blueprint_hash"]


def test_the_manifest_binds_artifacts_to_the_blueprint_that_produced_them(
    plate, built, tmp_path
):
    """The hash an approval binds to, carried by the files it authorised.

    Without it a stored artifact and its contract can only be associated by
    assumption, and a mismatch is undetectable rather than merely unlikely.
    """
    bundle = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["blueprint_hash"] == bundle["blueprint"]["blueprint_hash"]


def test_an_absent_manifest_reads_as_absent_rather_than_raising(tmp_path):
    """Every artifact built before manifests existed has none."""
    assert artifacts.read_manifest(str(tmp_path)) is None
    assert artifacts.manifest_entry(None, "part.step") is None


def test_a_corrupt_manifest_is_treated_as_missing(tmp_path):
    """A record that cannot be parsed must not take the download with it."""
    (tmp_path / artifacts.MANIFEST_NAME).write_text("{not json", encoding="utf-8")

    assert artifacts.read_manifest(str(tmp_path)) is None


# --------------------------------------------------------------------------- #
# the stamps
# --------------------------------------------------------------------------- #
def test_the_service_build_is_stamped_on_success_and_on_failure(
    plate, built, monkeypatch
):
    """The bundle keys must not depend on whether the kernel succeeded.

    A caller reading a bundle should not have to know which one it got, and the
    failed builds are exactly the ones whose provenance is worth having.
    """
    monkeypatch.setenv("ORIONFLOW_BUILD", "abc1234")

    ok = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})
    assert ok["success"] is True
    assert ok["builder"] == "abc1234"

    failed = built(plate, {}, returncode=1)
    assert failed["success"] is False
    assert failed["builder"] == "abc1234"
    assert failed["artifact_digests"] == {}


def test_an_unstamped_deploy_says_so(monkeypatch):
    """``unknown`` rather than an empty string, matching what /health reports."""
    monkeypatch.delenv("ORIONFLOW_BUILD", raising=False)

    assert artifacts.builder_stamp() == "unknown"


def test_the_topology_sidecar_is_an_artifact_like_any_other(plate, built):
    """Digested, manifested and uploaded with the geometry it describes.

    It is the only record of which feature authored which face — a STEP is a
    finished solid with no feature tree — so a copy that cannot be checked
    against its build is worth little.
    """
    sidecar = json.dumps(
        {
            "schema": "orionflow-topology-v1",
            "attribution": "element_map",
            "counts": {"faces": 1},
            "faces": [{"ref": "#o1.s1.f1", "index": 1, "feature": "base_pad"}],
            "features": {
                "base_pad": {
                    "type": "PartDesign::Pad",
                    "faces": ["#o1.s1.f1"],
                    "edges": [],
                    "vertices": [],
                }
            },
        }
    )
    bundle = built(
        plate,
        {
            "part.step": "ISO-10303-21;",
            "part.stl": "solid",
            "part.topology.json": sidecar,
        },
    )

    assert bundle["files"]["topology"].endswith("/part.topology.json")
    assert bundle["artifact_digests"]["topology"]["bytes"] == len(sidecar)

    # The bundle carries the summary, not the record: the full sidecar is
    # megabytes on a dense part and every caller would pay for it.
    assert bundle["topology"]["counts"]["faces"] == 1
    assert bundle["topology"]["features"]["base_pad"]["faces"] == 1
    assert "faces" not in bundle["topology"]


def test_a_build_without_topology_reports_none_rather_than_failing(plate, built):
    """Extraction is best-effort; a part the user can download is still a part."""
    bundle = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})

    assert bundle["success"] is True
    assert bundle["topology"] == {}
    assert "topology" not in bundle["files"]


def test_the_kernel_version_reaches_the_bundle_and_the_record(plate, built):
    """Reported by the container that compiled, since nothing else knows it."""
    bundle = built(
        plate,
        {"part.step": "ISO-10303-21;", "part.stl": "solid"},
        measured={"kernel": {"freecad": "1.1.0"}},
    )

    assert bundle["kernel"] == {"freecad": "1.1.0"}
    assert sp.build_evidence(bundle)["kernel"] == {"freecad": "1.1.0"}


def test_the_record_keeps_the_digests_out_of_the_url_map(plate, built):
    """``artifacts`` stays a flat kind→URL map, because callers iterate it.

    The UI renders one download per key and ``build_completed`` lists the keys.
    Nesting the digests inside it would have both report a file that does not
    exist, so they travel beside it.
    """
    bundle = built(plate, {"part.step": "ISO-10303-21;", "part.stl": "solid"})
    evidence = sp.build_evidence(bundle)

    assert set(evidence["artifacts"]) <= {"fcstd", "step", "stl", "glb"}
    assert all(isinstance(v, str) for v in evidence["artifacts"].values())
    assert evidence["artifact_digests"]["step"]["sha256"]
