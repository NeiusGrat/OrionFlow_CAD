"""The calculators, wired into the verdict.

`orion.calc` held seventeen correct calculators that nothing on the live build
path ever called, so VERIFIED was a true statement about shape that said nothing
about whether the part survives its duty. These pin the wiring.

The load-bearing property is that a calculator's *dimensions* come from the same
frozen variables the geometry was built from. A design that could author an 8 mm
plate and check the stress on a 20 mm one would produce two internally
consistent numbers and one wrong part.
"""

import pytest

from orion import engineering
from orion_physical_ai import verify

VARS = {"w": 40.0, "t": 8.0, "arm": 200.0}


def bp(checks=None, material=None):
    block = {}
    if material:
        block["material"] = material
    if checks is not None:
        block["checks"] = checks
    return {"design_plan": {"engineering": block}} if block else {"design_plan": {}}


MEASURED = {
    "body_volume": 64000.0,
    "bbox": [0, 0, 0, 200, 40, 8],
    "valid": True,
    "solids": 1,
}


# --------------------------------------------------------------------------- #
# nothing declared, nothing changes
# --------------------------------------------------------------------------- #
def test_a_design_that_declares_nothing_gets_no_checks():
    """Every Blueprint in the existing corpus is this case."""
    assert engineering.run_checks({"design_plan": {}}, VARS, MEASURED) == []
    assert engineering.observations({"design_plan": {}}, MEASURED) == {}


def test_a_missing_design_plan_is_not_an_error():
    assert engineering.run_checks({}, VARS, MEASURED) == []


# --------------------------------------------------------------------------- #
# dimensions come from the frozen variables
# --------------------------------------------------------------------------- #
def test_dimensions_are_taken_from_the_blueprints_own_variables():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "arm",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.5}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    assert len(rows) == 1
    r = rows[0]
    # b*h^3/12 with the *declared* 40 x 8, not anything re-stated.
    assert r["result"]["width_mm"] == 40.0
    assert r["result"]["height_mm"] == 8.0
    assert r["result"]["length_mm"] == 200.0


def test_an_expression_over_variables_is_evaluated():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "e",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 10.0,
                        "length_mm": "=arm/2",
                        "width_mm": "=w",
                        "height_mm": "=t*2",
                        "material_name": "steel_1018",
                    },
                }
            ],
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["result"]["length_mm"] == 100.0
    assert rows[0]["result"]["height_mm"] == 16.0


def test_a_measured_quantity_can_be_referenced():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "@material"},
                    "expect": {"mass_g": {"max": 200.0}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    # 64000 mm^3 of 6061 is 172.8 g, under the 200 g budget.
    assert rows[0]["passed"] is True
    assert round(rows[0]["result"]["mass_g"], 1) == 172.8


def test_referencing_something_the_kernel_never_measured_fails_the_check():
    """Not silently zero — a stress on a zero dimension is worse than none."""
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "@material"},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        measured={},
    )

    assert rows[0]["passed"] is False
    assert "no volume" in rows[0]["detail"]


# --------------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------------- #
def test_a_part_that_misses_its_safety_factor_fails():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "arm",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.5}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    # 196 N at 200 mm on 40x8 aluminium: sigma = 6FL/bh^2 = 91.9 MPa,
    # yield 276 -> SF 3.0. Comfortably passes.
    assert rows[0]["passed"] is True

    thin = engineering.run_checks(
        bp(
            [
                {
                    "id": "arm",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.5}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        {"w": 40.0, "t": 3.0, "arm": 200.0},
        MEASURED,
    )

    # Same load on a 3 mm section: SF drops below 1.
    assert thin[0]["passed"] is False
    assert "below the required minimum" in thin[0]["detail"]


def test_a_max_bound_is_enforced():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "@material"},
                    "expect": {"mass_g": {"max": 100.0}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["passed"] is False
    assert "exceeds the allowed maximum" in rows[0]["detail"]


def test_a_bound_on_an_output_the_calculator_does_not_have_fails_loudly():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "@material"},
                    "expect": {"stiffness": {"min": 1.0}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["passed"] is False
    assert "not one of this calculator's outputs" in rows[0]["detail"]


# --------------------------------------------------------------------------- #
# a declared check that cannot run is a failure, not a silence
# --------------------------------------------------------------------------- #
def test_an_unknown_calculator_fails_the_check():
    rows = engineering.run_checks(
        bp([{"id": "x", "calc": "buckling", "args": {}}]), VARS, MEASURED
    )

    assert rows[0]["passed"] is False
    assert "no calculator named 'buckling'" in rows[0]["detail"]


def test_an_unknown_material_fails_the_check():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "unobtainium"},
                }
            ],
            material="unobtainium",
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["passed"] is False
    assert "unknown material" in rows[0]["detail"]


def test_an_expression_over_an_undeclared_variable_fails_the_check():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "e",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 10.0,
                        "length_mm": "=nonexistent",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "steel_1018",
                    },
                }
            ]
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["passed"] is False
    assert "could not resolve arguments" in rows[0]["detail"]


# --------------------------------------------------------------------------- #
# ran, but nothing was claimed
# --------------------------------------------------------------------------- #
def test_a_calculator_with_no_bound_is_an_observation_not_a_pass():
    rows = engineering.run_checks(
        bp(
            [
                {
                    "id": "m",
                    "calc": "mass_properties",
                    "args": {"volume_mm3": "@volume", "material_name": "@material"},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    assert rows[0]["passed"] is None, "no declared bound means nothing to tick"
    assert "mass_g" in rows[0]["detail"]


def test_an_ungraded_row_never_becomes_a_green_check():
    """The 'assumed pass' the verifier exists to refuse."""
    rows = [
        {
            "id": "m",
            "label": "Mass",
            "calc": "mass_properties",
            "passed": None,
            "detail": "mass_g=172.8",
            "result": {},
            "expect": {},
        }
    ]

    assert verify.engineering_checks(rows) == []


# --------------------------------------------------------------------------- #
# the verdict
# --------------------------------------------------------------------------- #
def test_a_failed_engineering_check_refuses_a_geometrically_perfect_part():
    """The whole point: the shape is right and the part is not good enough."""
    geometry = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    eng = engineering.run_checks(
        bp(
            [
                {
                    "id": "arm",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.5}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        {"w": 40.0, "t": 3.0, "arm": 200.0},
        MEASURED,
    )

    report = verify.from_assertion_rows(
        geometry, measured={"valid": True, "solids": 1}, engineering=eng
    )

    assert report["verdict"] == "refused"
    assert "eng:arm" in [c["id"] for c in report["failed"]]


def test_a_passing_engineering_check_still_verifies():
    geometry = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    eng = engineering.run_checks(
        bp(
            [
                {
                    "id": "arm",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.5}},
                }
            ],
            material="aluminium_6061_t6",
        ),
        VARS,
        MEASURED,
    )

    report = verify.from_assertion_rows(
        geometry, measured={"valid": True, "solids": 1}, engineering=eng
    )

    assert report["verdict"] == "verified"
    assert "eng:arm" in [c["id"] for c in report["checks"]]


def test_engineering_is_absent_from_a_report_that_declared_none():
    """No new checks appear for the corpus, so no published number moves."""
    report = verify.from_assertion_rows(
        [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 0.0}],
        measured={"valid": True, "solids": 1},
        engineering=engineering.run_checks({"design_plan": {}}, VARS, MEASURED),
    )

    assert not any(c["id"].startswith("eng:") for c in report["checks"])
    assert report["verdict"] == "verified"


# --------------------------------------------------------------------------- #
# mass, for free, when a material is named
# --------------------------------------------------------------------------- #
def test_mass_is_reported_whenever_a_material_is_declared():
    obs = engineering.observations(bp(material="steel_1018"), MEASURED)

    assert obs["material"] == "steel_1018"
    assert round(obs["mass_g"], 1) == 503.7  # 64000 mm^3 x 7870 kg/m^3


def test_no_material_means_no_guessed_density():
    assert engineering.observations(bp(), MEASURED) == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"design_plan": {"engineering": "nonsense"}},
        {"design_plan": {"engineering": {"checks": 5}}},
    ],
)
def test_a_malformed_block_does_not_crash_the_build(bad):
    assert engineering.run_checks(bad, VARS, MEASURED) == []


# --------------------------------------------------------------------------- #
# the static checker
# --------------------------------------------------------------------------- #
def _plate(design_plan):
    """A minimal buildable plate, with `arm` used only by the engineering block."""
    return {
        "part_class": "bracket",
        "variables": {"w": 40.0, "d": 50.0, "t": 8.0, "arm": 200.0},
        "datums": {},
        "design_plan": design_plan,
        "assertions": [
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "target": "w*d*t",
                "tol_rel": 1e-6,
            }
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "plate", "type": "Pad", "parameters": {"Length": "t"}},
            ],
            "sketches": [
                {
                    "id": "s0",
                    "plane": "XY",
                    "profile": {"builder": "rect", "args": {"w": "w", "h": "d"}},
                }
            ],
            "dependencies": [{"kind": "profile", "source": "s0", "target": "plate"}],
        },
    }


ENG = {
    "engineering": {
        "material": "aluminium_6061_t6",
        "checks": [
            {
                "id": "arm_stress",
                "calc": "beam_bending",
                "args": {
                    "load_n": 196.0,
                    "length_mm": "=arm",
                    "width_mm": "=w",
                    "height_mm": "=t",
                    "material_name": "@material",
                },
                "expect": {"safety_factor": {"min": 1.5}},
            }
        ],
    }
}


def test_a_variable_used_only_by_a_calculator_is_not_reported_unused():
    """`arm` appears in no feature and no assertion — only in the check.

    Without teaching the checker this scope it reads as "a magic number in
    disguise" and refuses a correct design, which is the bug the pattern-count
    arguments once had.
    """
    from orion.blueprint import Blueprint

    bp = Blueprint.from_dict(_plate(ENG)).freeze()
    assert bp.blueprint_hash


def test_an_engineering_expression_over_an_unknown_variable_is_refused_at_freeze():
    """Caught statically, before a kernel is ever started."""
    from orion.blueprint import Blueprint, BlueprintError

    broken = {
        "engineering": {
            "material": "aluminium_6061_t6",
            "checks": [
                {
                    "id": "s",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 1.0,
                        "length_mm": "=nope",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                }
            ],
        }
    }

    with pytest.raises(BlueprintError, match="nope"):
        Blueprint.from_dict(_plate(broken)).freeze()


def test_the_engineering_block_is_part_of_the_frozen_contract():
    """It is authored intent, so changing it must change the hash."""
    from orion.blueprint import Blueprint

    a = Blueprint.from_dict(_plate(ENG)).freeze().blueprint_hash
    loosened = {
        "engineering": {
            "material": "aluminium_6061_t6",
            "checks": [
                {
                    "id": "arm_stress",
                    "calc": "beam_bending",
                    "args": {
                        "load_n": 196.0,
                        "length_mm": "=arm",
                        "width_mm": "=w",
                        "height_mm": "=t",
                        "material_name": "@material",
                    },
                    "expect": {"safety_factor": {"min": 1.0}},
                }
            ],
        }
    }
    b = Blueprint.from_dict(_plate(loosened)).freeze().blueprint_hash

    assert a != b, "relaxing a safety factor must not be invisible to the hash"
