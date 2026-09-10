"""The frame solver, checked against things whose answers are already known.

A solver nobody validated is a random number generator with units. Two kinds of
check here, and the second is the one that matters:

*Against our own closed form.* A frame of one prismatic member must reproduce
:func:`orion.calc.beam_bending` to machine precision, because a two-node
Timoshenko element's stiffness matrix *is* the exact solution of the beam
equation. If these ever disagree, one of the two is wrong and neither can be
trusted until it is settled.

*Against an independent derivation.* Reproducing our own formula proves the
element; it says nothing about whether members are assembled, transformed and
restrained correctly. The L-frame below is worked out by hand from virtual
work — a separate route to the same number — and that is what tests the
assembly.
"""

import math

import pytest

from orion import calc, fem

STEEL = calc.material("steel_1018")
E, NU = STEEL["E"], STEEL["nu"]
G = E / (2.0 * (1.0 + NU))
KAPPA = 5.0 / 6.0


# --------------------------------------------------------------------------- #
# One member: must equal the closed form exactly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("length,width,height,load", [
    (100.0, 10.0, 10.0, 100.0),      # the report's benchmark cantilever
    (200.0, 20.0, 5.0, 50.0),        # slender
    (20.0, 10.0, 10.0, 100.0),       # L/H = 2, where shear carries 16%
    (15.0, 10.0, 10.0, 250.0),       # stubbier still
])
def test_a_single_member_frame_reproduces_the_closed_form(length, width,
                                                          height, load):
    closed = calc.beam_bending(load_n=load, length_mm=length, width_mm=width,
                               height_mm=height, material_name="steel_1018")
    solved = fem.solve(
        fem.cantilever_frame(length, width, height, load, E, NU))

    assert solved.deflection_at(1) == pytest.approx(
        closed["deflection_mm"], rel=1e-9)
    assert solved.max_stress_mpa == pytest.approx(
        closed["max_stress_mpa"], rel=1e-9)


def test_the_element_carries_shear_like_the_closed_form_does():
    """The correction that was missing from `beam_bending` until it was found
    underpredicting a stubby beam by 16%. Both must have it or neither."""
    closed = calc.beam_bending(load_n=100.0, length_mm=20.0, width_mm=10.0,
                               height_mm=10.0, material_name="steel_1018")
    solved = fem.solve(fem.cantilever_frame(20.0, 10.0, 10.0, 100.0, E, NU))

    # Euler-Bernoulli alone would be 16% low here.
    assert solved.deflection_at(1) > closed["deflection_bending_mm"] * 1.10
    assert solved.deflection_at(1) == pytest.approx(closed["deflection_mm"],
                                                    rel=1e-9)


# --------------------------------------------------------------------------- #
# Two members: an independent hand derivation
# --------------------------------------------------------------------------- #


def test_an_l_frame_matches_a_hand_derivation():
    """Virtual work, by a route the solver does not take.

    Horizontal tip deflection of an L-frame fixed at the far end of its base:

        upright bending    P b^3 / (3 E I_up)
        base bending       (P b) a / (E I_base), the corner rotation swung
                           through the upright's height
        base axial         P a / (E A_base)
        shear              P b / (kappa G A_up)
    """
    p, a, b = 50.0, 200.0, 200.0
    bw, bt, uw, ut = 20.0, 5.0, 20.0, 5.0
    i_base, i_up = bw * bt ** 3 / 12.0, uw * ut ** 3 / 12.0

    hand = (p * b ** 3 / (3 * E * i_up)
            + p * b ** 2 * a / (E * i_base)
            + p * a / (E * bw * bt)
            + p * b / (KAPPA * G * uw * ut))

    frame = fem.Frame(
        nodes=[(0.0, 0.0), (a, 0.0), (a, b)],
        members=[fem.Member(0, 1, fem.Section(bw, bt), "base"),
                 fem.Member(1, 2, fem.Section(uw, ut), "upright")],
        supports={0: "xzr"}, loads={2: (p, 0.0, 0.0)},
        modulus=E, poisson=NU,
    )
    solution = fem.solve(frame)

    assert solution.displacements[2][0] == pytest.approx(hand, rel=1e-6)


def test_the_base_carries_the_uprights_moment():
    """The physics the single-cantilever model was missing entirely."""
    p, a, b = 50.0, 200.0, 200.0
    section = fem.Section(20.0, 5.0)
    frame = fem.Frame(
        nodes=[(0.0, 0.0), (a, 0.0), (a, b)],
        members=[fem.Member(0, 1, section, "base"),
                 fem.Member(1, 2, section, "upright")],
        supports={0: "xzr"}, loads={2: (p, 0.0, 0.0)},
        modulus=E, poisson=NU,
    )
    solution = fem.solve(frame)
    base = next(m for m in solution.members if m.name == "base")

    # Moment at the support is the load times the upright's height.
    assert base.moment_nmm == pytest.approx(p * b, rel=1e-9)
    assert base.bending_mpa == pytest.approx(
        p * b * section.extreme_fibre / section.inertia, rel=1e-9)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_a_mechanism_is_refused_rather_than_solved():
    """An unrestrained structure has no static solution, and returning one
    would be numbers that look like an answer."""
    frame = fem.Frame(
        nodes=[(0.0, 0.0), (100.0, 0.0)],
        members=[fem.Member(0, 1, fem.Section(10.0, 10.0), "beam")],
        supports={},                       # nothing held
        loads={1: (0.0, -100.0, 0.0)},
        modulus=E, poisson=NU,
    )
    with pytest.raises(fem.FrameError, match="mechanism"):
        fem.solve(frame)


def test_a_partially_restrained_structure_is_still_a_mechanism():
    """Pinned at one node only: it can still rotate about the pin."""
    frame = fem.Frame(
        nodes=[(0.0, 0.0), (100.0, 0.0)],
        members=[fem.Member(0, 1, fem.Section(10.0, 10.0), "beam")],
        supports={0: "xz"},                # free to rotate
        loads={1: (0.0, -100.0, 0.0)},
        modulus=E, poisson=NU,
    )
    with pytest.raises(fem.FrameError):
        fem.solve(frame)


@pytest.mark.parametrize("width,height", [(0.0, 10.0), (10.0, 0.0),
                                          (-5.0, 10.0)])
def test_a_section_with_no_material_is_refused(width, height):
    with pytest.raises(fem.FrameError):
        fem.Section(width, height)


def test_an_upright_that_does_not_clear_its_base_is_refused():
    with pytest.raises(fem.FrameError):
        fem.l_bracket_frame(base_length=80.0, base_width=60.0,
                            base_thickness=10.0, upright_height=10.0,
                            upright_width=60.0, upright_thickness=10.0,
                            load_n=100.0, modulus=E, poisson=NU)


# --------------------------------------------------------------------------- #
# Through the calculator
# --------------------------------------------------------------------------- #


def test_the_calculator_names_the_member_that_is_worst():
    """"Which part of the bracket is the problem" is half the answer."""
    result = calc.frame_l_bracket(
        load_n=400.0, base_length_mm=80.0, base_width_mm=60.0,
        base_thickness_mm=2.0, upright_height_mm=70.0,
        upright_width_mm=60.0, upright_thickness_mm=12.0,
        material_name="aluminium_6061_t6")

    assert result["worst_member"] == "base"
    assert result["base_stress_mpa"] > result["upright_stress_mpa"]


def test_thinning_the_base_costs_safety_factor():
    """The regression guard for the hole this solver was written to close."""
    common = dict(load_n=400.0, base_length_mm=80.0, base_width_mm=60.0,
                  upright_height_mm=70.0, upright_width_mm=60.0,
                  upright_thickness_mm=10.0,
                  material_name="aluminium_6061_t6")
    thick = calc.frame_l_bracket(base_thickness_mm=10.0, **common)
    thin = calc.frame_l_bracket(base_thickness_mm=1.0, **common)

    assert thick["safety_factor"] > 10.0
    assert thin["safety_factor"] < 1.0


def test_the_calculator_states_what_its_stress_is():
    """Nominal section, no concentration — said on the result rather than
    discovered when somebody trusts it."""
    result = calc.frame_l_bracket(
        load_n=100.0, base_length_mm=80.0, base_width_mm=60.0,
        base_thickness_mm=8.0, upright_height_mm=70.0,
        upright_width_mm=60.0, upright_thickness_mm=8.0,
        material_name="aluminium_6061_t6")

    assert "nominal" in result["stress_basis"]
    assert "no stress concentration" in result["stress_basis"]
    assert result["model"] == "frame"


def test_the_solver_adds_no_dependency_beyond_numpy():
    """Small dense systems. Pulling in a sparse solver for a 12x12 matrix
    would add a deployment dependency for nothing."""
    import inspect

    source = inspect.getsource(fem)
    assert "import scipy" not in source
    assert "from scipy" not in source
