"""The analytic tier, fed by the deterministic builders.

`orion.engineering` has run the calculators against the built solid since
2026-08-05, and `verify.engineering_checks` has gated the verdict on them for
just as long. Nothing ever declared a check: `blueprint_gen` wrote a
`manufacturing` block and never an `engineering` one, and 0 of 1,044 corpus
rows carried one. The tier was built and starved.

These pin the producer. The load-bearing properties are all about restraint:

* a request that states no load gets no check, not a check against a guessed
  duty — the same rule `manufacturing` and `tolerance` already run on
* a family that cannot honestly be read as a beam gets no check even when a
  load *is* stated
* the section that is graded comes from the frozen variables, so a design
  cannot author one upright and be checked on another
* the stress that gates is root stress, and stays distinct from the
  region-based metric an FEA verifier would report
"""

import pytest

from orion import blueprint_gen as G, engineering
from orion_physical_ai import verify

PLATE = {"length": 120.0, "width": 80.0, "thickness": 10.0}

BRACKET = {
    "base_length": 80.0, "base_width": 60.0, "base_thickness": 6.0,
    "upright_height": 70.0, "upright_thickness": 6.0,
}

MEASURED = {"body_volume": 1.0e5, "watertight": True, "valid": True,
            "solids": 1}


def _rows(bp):
    return engineering.run_checks(bp, bp["variables"], MEASURED)


def _verdict(rows):
    return verify.verdict_for(verify.engineering_checks(rows))


# --------------------------------------------------------------------------- #
# When a block is emitted at all
# --------------------------------------------------------------------------- #


def test_a_geometry_only_request_declares_nothing():
    """Every Blueprint in the existing corpus is this case."""
    bp = G.generate("rect_plate", dict(PLATE))
    assert "engineering" not in bp["design_plan"]


def test_a_load_with_no_material_cannot_become_a_stress():
    bp = G.generate("rect_plate", {**PLATE, "load_n": 500.0})
    assert "engineering" not in bp["design_plan"]


def test_a_material_with_no_load_is_just_a_density():
    bp = G.generate("rect_plate", {**PLATE, "material": "aluminium 6061 t6"})
    assert "engineering" not in bp["design_plan"]


def test_a_material_the_calculators_cannot_resolve_declares_nothing():
    """Better silent than graded against invented properties."""
    bp = G.generate("rect_plate", {**PLATE, "load_n": 500.0,
                                   "material": "unobtainium"})
    assert "engineering" not in bp["design_plan"]


def test_a_stated_load_and_material_declare_a_check():
    bp = G.generate("rect_plate", {**PLATE, "load_n": 500.0,
                                   "material": "aluminium 6061 t6"})
    block = bp["design_plan"]["engineering"]
    assert block["material"] == "aluminium_6061_t6"
    assert len(block["checks"]) == 1
    assert block["checks"][0]["calc"] == "beam_bending"


@pytest.mark.parametrize("family,req", [
    # Resolved names — `interview.resolve` has already halved diameters.
    ("disc", {"outer_r": 40.0, "thickness": 10.0}),
    ("shelled_box", {"length": 80.0, "width": 60.0, "height": 40.0,
                     "wall": 3.0}),
])
def test_a_family_that_is_not_a_beam_gets_no_beam_check(family, req):
    """A load through a bore or a thin wall is not a rectangular cantilever.

    Declaring one anyway would put a defensible-looking safety factor on a
    part whose loading it does not describe, which is worse than silence.
    """
    bp = G.generate(family, {**req, "load_n": 500.0,
                             "material": "aluminium 6061 t6"})
    assert "engineering" not in bp["design_plan"]


# --------------------------------------------------------------------------- #
# The section that gets graded is the section that was built
# --------------------------------------------------------------------------- #


def test_dimensions_are_expressions_over_the_frozen_variables():
    """Never literals. This is the property that stops a design authoring an
    8 mm upright and grading a 20 mm one."""
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6"})
    args = bp["design_plan"]["engineering"]["checks"][0]["args"]

    assert args["length_mm"] == "=UH"
    assert args["width_mm"] == "=UW"
    assert args["height_mm"] == "=UT"
    assert args["material_name"] == "@material"
    # The load is the one fact about the world rather than the part.
    assert args["load_n"] == 300.0


def test_the_graded_section_follows_the_geometry_it_was_built_from():
    thin = G.generate("l_bracket", {**BRACKET, "upright_thickness": 4.0,
                                    "load_n": 300.0,
                                    "material": "aluminium 6061 t6"})
    thick = G.generate("l_bracket", {**BRACKET, "upright_thickness": 12.0,
                                     "load_n": 300.0,
                                     "material": "aluminium 6061 t6"})

    thin_sf = _rows(thin)[0]["result"]["safety_factor"]
    thick_sf = _rows(thick)[0]["result"]["safety_factor"]

    # I = w*h^3/12, so tripling the thickness is roughly a ninefold gain.
    assert thick_sf > thin_sf * 8


def test_the_bending_dimension_is_the_thickness_not_the_width():
    """The load bends the upright *through* its thickness.

    Getting this backwards produces a number that looks fine and describes the
    wrong axis, which is exactly the failure the mapping is declared to avoid.
    """
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6"})
    r = _rows(bp)[0]["result"]

    assert r["height_mm"] == bp["variables"]["UT"] == 6.0
    assert r["width_mm"] == bp["variables"]["UW"] == 60.0


# --------------------------------------------------------------------------- #
# Reaching the tier, and failing it
# --------------------------------------------------------------------------- #


def test_a_generated_block_reaches_the_analytic_tier():
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 50.0,
                                  "material": "aluminium 6061 t6"})
    rows = _rows(bp)

    assert len(rows) == 1
    assert rows[0]["calc"] == "beam_bending"
    # Graded, not merely observed.
    assert rows[0]["passed"] is True
    assert rows[0]["result"]["max_stress_mpa"] > 0
    assert _verdict(rows) == verify.VERIFIED


def test_a_violated_safety_factor_refuses_the_part():
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 2000.0,
                                  "material": "aluminium 6061 t6"})
    rows = _rows(bp)

    assert rows[0]["passed"] is False
    assert rows[0]["result"]["safety_factor"] < 1.5
    assert _verdict(rows) == verify.REFUSED


def test_a_violated_deflection_limit_refuses_the_part():
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6",
                                  "max_deflection_mm": 0.05})
    rows = _rows(bp)

    assert rows[0]["result"]["deflection_mm"] > 0.05
    assert rows[0]["passed"] is False
    assert _verdict(rows) == verify.REFUSED


def test_a_deflection_within_its_limit_passes():
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6",
                                  "max_deflection_mm": 2.0})
    rows = _rows(bp)

    assert rows[0]["passed"] is True
    assert _verdict(rows) == verify.VERIFIED


def test_an_unstated_deflection_limit_is_reported_not_graded():
    """A number nobody bounded is an observation, never a green tick."""
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6"})
    check = bp["design_plan"]["engineering"]["checks"][0]

    assert "deflection_mm" not in check["expect"]
    # It still gets computed and carried.
    assert _rows(bp)[0]["result"]["deflection_mm"] > 0


# --------------------------------------------------------------------------- #
# Assumptions are recorded, never silent
# --------------------------------------------------------------------------- #


def test_an_unstated_support_defaults_conservatively_and_says_so():
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6"})
    block = bp["design_plan"]["engineering"]

    assert block["checks"][0]["args"]["case"] == "cantilever_end"
    assert "support" in block["assumptions"]
    assert "safety_factor" in block["assumptions"]


def test_a_stated_support_is_used_and_raises_no_assumption():
    bp = G.generate("rect_plate", {**PLATE, "load_n": 300.0,
                                   "material": "aluminium 6061 t6",
                                   "support": "supported both ends",
                                   "safety_factor": 2.0})
    block = bp["design_plan"]["engineering"]

    assert block["checks"][0]["args"]["case"] == "simply_supported_centre"
    assert block["checks"][0]["expect"]["safety_factor"]["min"] == 2.0
    assert "assumptions" not in block


def test_the_conservative_default_is_the_pessimistic_one():
    """A defaulted support may refuse a part a truer model would pass. It must
    never pass one a truer model would refuse."""
    common = {**PLATE, "load_n": 800.0, "material": "aluminium 6061 t6"}
    defaulted = G.generate("rect_plate", dict(common))
    supported = G.generate("rect_plate", {**common,
                                          "support": "supported both ends"})

    assert (_rows(defaulted)[0]["result"]["safety_factor"]
            < _rows(supported)[0]["result"]["safety_factor"])


# --------------------------------------------------------------------------- #
# Frozen before the build
# --------------------------------------------------------------------------- #


def test_the_declared_duty_is_inside_the_blueprint_hash():
    """The check runs after the build, so the duty has to be committed before
    one — the same argument as the manufacturing block and the assertions."""
    from orion.blueprint import Blueprint

    base = {**BRACKET, "load_n": 300.0, "material": "aluminium 6061 t6"}
    a = Blueprint.from_dict(G.generate("l_bracket", base)).freeze()
    heavier = Blueprint.from_dict(
        G.generate("l_bracket", {**base, "load_n": 900.0})).freeze()
    looser = Blueprint.from_dict(
        G.generate("l_bracket", {**base, "safety_factor": 1.1})).freeze()

    assert a.blueprint_hash != heavier.blueprint_hash, \
        "restating the load must not be invisible to the hash"
    assert a.blueprint_hash != looser.blueprint_hash, \
        "relaxing the required factor must not be invisible to the hash"


def test_the_stress_basis_is_recorded_as_root():
    """Root stress and an FEA region metric are different numbers and both are
    correct. The block says which one it is so the two cannot be quietly
    reconciled later — see the note in blueprint_gen._engineering."""
    bp = G.generate("l_bracket", {**BRACKET, "load_n": 300.0,
                                  "material": "aluminium 6061 t6"})
    block = bp["design_plan"]["engineering"]

    assert block["stress_basis"].startswith("root:")
    assert block["models"]
