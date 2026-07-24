"""Static regression over all recipe families — no FreeCAD required.

Every family must, across several seeds: freeze (checker-clean), resolve
(profiles buildable, expressions evaluable), carry at least one fault whose
mutation actually changes the frozen hash, and declare a body-volume or
volume-between assertion so the forge always has a mass property to verify.
"""

import random

import pytest

from orion.blueprint import Blueprint
from orion.recipes import RECIPES

SEEDS = [7, 101, 350]


def _draw(name, seed):
    """First feasible draw at or after ``seed`` (recipes may reject a draw)."""
    for s in range(seed, seed + 40):
        rng = random.Random(s)
        try:
            return RECIPES[name](rng)
        except ValueError:
            continue
    raise AssertionError(f"{name}: no feasible draw in 40 attempts")


def test_family_count():
    assert len(RECIPES) >= 18


@pytest.mark.parametrize("name", sorted(RECIPES))
@pytest.mark.parametrize("seed", SEEDS)
def test_freeze_and_resolve(name, seed):
    bp, faults, seq = _draw(name, seed)
    assert bp.blueprint_hash and bp.verify_hash()
    graph = bp.resolve()
    assert graph["features"] and graph["sketches"]
    assert graph["_analysis"], "profile analysis missing"
    kinds = {a.get("kind") for a in bp.assertions}
    assert kinds & {"body_volume", "volume_between", "body_mesh_converged"}, \
        f"{name}: no mass-property assertion"
    assert seq and all(isinstance(s, str) for s in seq)


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_fault_changes_the_contract(name):
    bp, faults, _seq = _draw(name, 7)
    assert faults, f"{name}: no fault palette"
    import copy
    for fname, (mutate, meta) in faults.items():
        t = copy.deepcopy(bp.template)
        v = dict(bp.variables)
        mutate(t, v)
        faulted = Blueprint(part_class=bp.part_class + "_f", variables=v,
                            datums=bp.datums, design_plan=bp.design_plan,
                            assertions=bp.assertions, template=t).freeze()
        assert faulted.blueprint_hash != bp.blueprint_hash, \
            f"{name}.{fname}: mutation did not change the blueprint"
        assert meta.get("diagnosis") and meta.get("fix"), \
            f"{name}.{fname}: repair metadata incomplete"


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_derivation_chain_present(name):
    bp, _f, _s = _draw(name, 7)
    chain = bp.design_plan.get("derivation", [])
    assert chain, f"{name}: empty derivation chain"
    assert all(step.get("eq") for step in chain)
