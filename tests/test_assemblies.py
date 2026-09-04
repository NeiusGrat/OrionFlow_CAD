"""Assemblies on the live path: many parts, placed, with their mates checked.

What an assembly proves that a single part cannot is **non-interference**, and
it proves it exactly. If no two components share space the fused volume equals
the sum of the component volumes, so the deficit *is* the interpenetration —
a machine-precision proof, not a similarity score.

These are unit tests over the catalogue and the translation into the studio's
bundle. The kernel-backed builds are exercised by the end-to-end run; here the
concern is that a family cannot be asked about without being buildable, that
every spec's parameters line up with the schema that collects them, and that
the interference check is wired to the verdict rather than merely computed.
"""

import pytest

from app.services import assembly_service as A
from orion import interview


def test_every_assembly_in_the_catalogue_is_in_the_schema():
    """Otherwise the interview can never collect what it needs."""
    for name in A.catalogue():
        assert name in interview.FAMILIES, name


def test_every_schema_slot_is_a_parameter_the_spec_accepts():
    """A slot the builder ignores is a question asked for nothing.

    The service maps slots onto the spec function by name, so a mismatch is
    silent: the user answers, the value is dropped, and the default is built
    instead.
    """
    import inspect

    for name, spec in A.catalogue().items():
        fam = interview.FAMILIES[name]
        accepted = set(inspect.signature(spec.fn).parameters)
        assert set(spec.params) <= accepted, (name, set(spec.params) - accepted)
        asked = {s.name for s in fam.required + fam.optional}
        assert asked <= set(spec.params), (name, asked - set(spec.params))


def test_every_required_slot_is_one_the_spec_needs():
    """Required means the assembly is not determined without it."""
    for name, spec in A.catalogue().items():
        for slot in interview.FAMILIES[name].required:
            assert slot.name in spec.params, (name, slot.name)


def test_counts_reach_the_spec_as_integers():
    """``n_bolts`` is a count. Passed through as 4.0 it would index nothing and
    the spec would build the wrong number of components."""
    spec = A.catalogue()["bolted_joint"]
    built = spec.make({"d": 10, "plate_t": 12, "n_bolts": 4.0, "cls": "8.8"})
    assert built["variables"]["n_bolts"] == 4.0
    assert sum(1 for c in built["components"] if c["id"].startswith("bolt")) == 4


def test_a_strength_class_stays_a_string():
    """8.8 is a designation, not a number; floating it loses the class."""
    spec = A.catalogue()["bolted_joint"]
    built = spec.make({"d": 8, "plate_t": 10, "cls": "10.9"})
    assert any("10.9" in str(m.get("constraint", "")) for m in built["mates"])


def test_a_bolted_joint_places_every_bolt_somewhere_different():
    """The defect the interference proof caught the first time it ran.

    Every bolt after the first was placed at ``+hole_dx`` — the same point — so
    a three-bolt joint stacked two bolts inside one another. It built, and the
    fusion came up 2.6% short of the component sum.
    """
    from orion import assembly_spec as S

    for n in (2, 3, 4, 6):
        built = S.bolted_joint(d=8.0, plate_t=10.0, n_bolts=n)
        xs = [c["pos"][0] for c in built["components"] if c["id"].startswith("bolt")]
        assert len(xs) == n
        assert len(set(round(x, 6) for x in xs)) == n, (n, xs)


def test_a_bolted_joint_drills_the_plate_for_every_bolt():
    """The other half: bolts placed correctly through a two-hole plate is the
    same bug wearing a different hat."""
    from orion import assembly_spec as S

    built = S.bolted_joint(d=8.0, plate_t=10.0, n_bolts=4)
    plate = next(c for c in built["components"] if c["id"] == "plate_lower")
    assert plate["params"]["n_holes"] == 4


def test_one_bolt_is_not_a_joint():
    from orion import assembly_spec as S

    with pytest.raises(ValueError, match="at least two bolts"):
        S.bolted_joint(n_bolts=1)


def test_a_clearance_plate_carries_the_holes_it_was_asked_for():
    from orion import families as F

    for n in (2, 3, 5):
        bp = F.make("clearance_plate", length=300.0, width=60.0, t=10.0,
                    hole_r=4.5, hole_dx=80.0, n_holes=n)
        holes = bp.template["sketches"][0]["profile"]["args"]["holes"]
        assert len(holes) == n
        body = next(a for a in bp.assertions if a["id"] == "body")
        # Parametric in the count, not a literal: a count the geometry depends
        # on and no expression mentions is a magic number.
        assert "n_holes*pi*hole_r**2*t" in body["target"]


def test_interference_is_a_failure_not_a_note():
    """The one property an assembly must have. A row that computes the deficit
    and does not gate the verdict would be decoration."""
    rows = A._checks({
        "assertions": [{"id": "no_interference", "kind": "no_interference",
                        "target": 100.0, "measured": 95.0, "rel_err": 5e-2,
                        "passed": False}],
        "parts": [],
    })
    assert rows[0]["status"] == "fail"
    assert "95" in rows[0]["detail"] and "100" in rows[0]["detail"]


def test_a_mechanism_that_cannot_close_refuses_instead_of_crashing():
    """A four-bar whose links cannot reach each other has no configuration to
    draw, and ``four_bar`` answers ``None`` for it.

    Subscripting that raised TypeError deep inside ``resolve_spec`` — a crash
    where a refusal belongs. The user got a stack trace instead of the reason.
    """
    out = A.build("four_bar", {"ground": 100, "crank": 300,
                               "coupler": 20, "rocker": 20})
    assert out["verification"]["verdict"] == "refused"
    assert out["files"] == {} and not out["success"]
    assert "cannot reach" in out["error"]


def test_a_spec_that_refuses_its_own_parameters_is_a_refusal_too():
    """``ValueError`` out of a catalogue spec is a statement about the request,
    not an exception to leak."""
    out = A.build("bolted_joint", {"d": 8, "plate_t": 10, "n_bolts": 1})
    assert out["verification"]["verdict"] == "refused"
    assert "at least two bolts" in out["error"]
