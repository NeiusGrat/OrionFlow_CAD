"""Assembling a part's feature history from three records that disagree.

The join between authored features and measured ones is the part that can go
quietly wrong, so most of these tests are about names: FreeCAD does not promise
to keep the id we hand it, and a mismatch shows up as a history tree full of
blank volumes rather than as an error.
"""

import pytest

from app.services import feature_tree

BLUEPRINT = {
    "version": "orion-blueprint-v1",
    "part_class": "plate",
    "variables": {"L": 50.0, "W": 30.0, "T": 5.0},
    "datums": {},
    "design_plan": {},
    "assertions": [],
    "template": {
        "sketches": [
            {
                "id": "Sketch",
                "plane": "XY",
                "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}},
            },
        ],
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "Sketch", "type": "Sketch", "parameters": {}},
            {"id": "Pad", "type": "Pad", "parameters": {"Length": "T"}},
            {"id": "Pocket", "type": "Pocket", "parameters": {"Length": "T / 2"}},
        ],
    },
    "blueprint_hash": "0123456789abcdef",
}

EVIDENCE = {
    "features": [
        {
            "name": "Pad",
            "type_id": "PartDesign::Pad",
            "addsub_volume": 7500.0,
            "cumulative_volume": 7500.0,
        },
        {
            "name": "Pocket",
            "type_id": "PartDesign::Pocket",
            "addsub_volume": -500.0,
            "cumulative_volume": 7000.0,
        },
    ],
    "recompute_errors": [],
    "unsupported": [],
    "verification": {"verdict": "verified"},
    "built_where": "modal",
}


def _by_id(tree):
    return {f["id"]: f for f in tree["features"]}


def test_structural_entries_are_not_features():
    """A Body and a Sketch are how the compiler works, not what the user did."""
    tree = feature_tree.build(BLUEPRINT, EVIDENCE)
    assert [f["id"] for f in tree["features"]] == ["Pad", "Pocket"]


def test_measured_volumes_are_attached():
    tree = feature_tree.build(BLUEPRINT, EVIDENCE)
    features = _by_id(tree)
    assert features["Pad"]["volume_delta_mm3"] == 7500.0
    assert features["Pocket"]["volume_delta_mm3"] == -500.0
    assert features["Pocket"]["cumulative_volume_mm3"] == 7000.0
    assert all(f["status"] == "success" for f in tree["features"])
    assert tree["evidence_available"] is True
    assert tree["verdict"] == "verified"


def test_expressions_resolve_to_numbers():
    """The tree shows both: the number built, and the expression behind it."""
    tree = feature_tree.build(BLUEPRINT, EVIDENCE)
    features = _by_id(tree)
    assert tree["parameters_resolved"] is True
    assert features["Pad"]["parameters"]["Length"] == 5.0
    assert features["Pocket"]["parameters"]["Length"] == 2.5
    assert features["Pad"]["expressions"]["Length"] == "T"


def test_a_renamed_freecad_object_still_matches():
    """FreeCAD sanitises names; equality alone would drop the volume."""
    evidence = {
        **EVIDENCE,
        "features": [
            {
                "name": "pad",
                "type_id": "PartDesign::Pad",
                "addsub_volume": 7500.0,
                "cumulative_volume": 7500.0,
            },
            {
                "name": "Pocket_001",
                "type_id": "PartDesign::Pocket",
                "addsub_volume": -500.0,
                "cumulative_volume": 7000.0,
            },
        ],
    }
    features = _by_id(feature_tree.build(BLUEPRINT, evidence))
    assert features["Pad"]["volume_delta_mm3"] == 7500.0
    # 'Pocket_001' normalises to 'pocket001', which is not 'pocket' — so this
    # one lands on the positional fallback, and must land on the right row.
    assert features["Pocket"]["volume_delta_mm3"] == -500.0


def test_one_measurement_is_never_claimed_twice():
    """Two features of a type, one measurement: the second stays unknown.

    Without the claim set, the positional fallback would hand the same row to
    both and report a volume for a feature nothing was measured for.
    """
    blueprint = {
        **BLUEPRINT,
        "template": {
            **BLUEPRINT["template"],
            "features": BLUEPRINT["template"]["features"]
            + [
                {"id": "Pocket2", "type": "Pocket", "parameters": {"Length": "T / 4"}},
            ],
        },
    }
    features = _by_id(feature_tree.build(blueprint, EVIDENCE))
    assert features["Pocket"]["volume_delta_mm3"] == -500.0
    assert features["Pocket2"]["volume_delta_mm3"] is None
    assert features["Pocket2"]["status"] == "unknown"


def test_a_failed_feature_carries_the_kernel_error():
    evidence = {
        **EVIDENCE,
        "recompute_errors": [
            {"id": "Pocket", "error": "invalid after recompute"},
        ],
    }
    features = _by_id(feature_tree.build(BLUEPRINT, evidence))
    assert features["Pocket"]["status"] == "error"
    assert features["Pocket"]["error"] == "invalid after recompute"
    assert features["Pad"]["status"] == "success"


def test_a_design_with_no_build_record_still_has_a_tree():
    """Volumes unknown, not zero — zero is a measurement nobody made."""
    tree = feature_tree.build(BLUEPRINT, None)
    features = _by_id(tree)
    assert tree["evidence_available"] is False
    assert [f["id"] for f in tree["features"]] == ["Pad", "Pocket"]
    assert features["Pad"]["volume_delta_mm3"] is None
    assert features["Pad"]["status"] == "unknown"
    # The authored side is entirely intact without any evidence.
    assert features["Pad"]["parameters"]["Length"] == 5.0


def test_an_unresolvable_blueprint_still_returns_its_features():
    """A stored blueprint we can no longer evaluate is still worth showing."""
    broken = {**BLUEPRINT, "variables": {}}  # every expression now references
    tree = feature_tree.build(broken, EVIDENCE)  # an unknown variable
    assert tree["parameters_resolved"] is False
    assert [f["id"] for f in tree["features"]] == ["Pad", "Pocket"]
    assert _by_id(tree)["Pad"]["expressions"]["Length"] == "T"
    # Measurement does not depend on resolution, so volumes survive.
    assert _by_id(tree)["Pad"]["volume_delta_mm3"] == 7500.0


@pytest.mark.parametrize("payload", [None, {}, {"template": {}}])
def test_empty_input_is_an_empty_tree_not_a_crash(payload):
    tree = feature_tree.build(payload)
    assert tree["features"] == []
    assert tree["evidence_available"] is False


def test_the_empty_tree_has_every_field_a_full_one_does():
    """The fallback must satisfy the same contract, or the client sees undefined."""
    full = feature_tree.build(BLUEPRINT, EVIDENCE)
    assert set(feature_tree.empty()) == set(full)
