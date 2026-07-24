"""Composition system regression — pure Python, no FreeCAD.

Guards the three bugs that composition shipped with, each of which produced a
part that BUILT CLEANLY and was silently wrong:

  1. attachment sketches added to ``sketches`` but never given ordered
     ``type: "Sketch"`` feature entries -> compiler reported "missing profile
     sketch" and skipped the attachment entirely;
  2. a mount ``thickness`` of "hubh - ft" spliced raw into a product ->
     ``pi*r**2*hubh - ft`` by operator precedence;
  3. a protruding attachment invalidating the base's z bbox_extent assertion.
"""

import random

import pytest

from orion import expr as E
from orion.bases import BASES
from orion.compose import ATTACHMENTS, MAX_ATTACHMENTS, compose

SEEDS = [11, 22, 33]


def _compose(name, seed, natt=None):
    # Some bases (tight geometric families like clevis/hx) reject a fraction of
    # draws as infeasible; retry from advancing seeds until one is feasible,
    # exactly as the production sampler does.
    for s in range(seed, seed + 60):
        rng = random.Random(s)
        try:
            draft = BASES[name](rng)
        except ValueError:
            continue
        return compose(draft, rng, n_attachments=natt)
    raise AssertionError(f"{name}: no feasible draw near seed {seed}")


def test_attachment_palette_present():
    assert len(ATTACHMENTS) >= 7


@pytest.mark.parametrize("name", sorted(BASES))
@pytest.mark.parametrize("seed", SEEDS)
def test_base_alone_freezes_and_resolves(name, seed):
    bp, meta = _compose(name, seed, natt=0)
    assert bp.verify_hash()
    g = bp.resolve()
    assert g["features"] and g["sketches"]
    assert meta["attachments"] == []
    assert meta["base_family"] == name


@pytest.mark.parametrize("name", sorted(BASES))
@pytest.mark.parametrize("seed", SEEDS)
def test_composed_part_is_wellformed(name, seed):
    bp, meta = _compose(name, seed, natt=MAX_ATTACHMENTS)
    g = bp.resolve()
    feature_ids = [f["id"] for f in g["features"]]
    sketch_ids = {s["id"] for s in g["sketches"]}

    # (1) every sketch has an ordered feature entry, before its consumer
    sketch_features = [f["id"] for f in g["features"] if f["type"] == "Sketch"]
    assert sketch_ids == set(sketch_features), \
        "sketch geometry without an ordered Sketch feature entry"
    for dep in g["dependencies"]:
        if dep["kind"] == "profile":
            assert feature_ids.index(dep["source"]) < \
                feature_ids.index(dep["target"]), \
                f"{dep['source']} must be built before {dep['target']}"

    # ids unique, deps resolvable
    assert len(feature_ids) == len(set(feature_ids))
    known = set(feature_ids) | sketch_ids
    for dep in g["dependencies"]:
        assert dep["source"] in known and dep["target"] in known


@pytest.mark.parametrize("name", sorted(BASES))
def test_body_expression_stays_evaluable(name):
    """(2) precedence: every composed body term must parse and evaluate —
    an unparenthesised mount thickness silently changed the arithmetic."""
    for seed in SEEDS:
        bp, _m = _compose(name, seed, natt=MAX_ATTACHMENTS)
        body = next(a for a in bp.assertions if a["id"] == "body")
        # A mesh-body base (irreducible union) has no closed-form target — the
        # body is verified numerically, so there is nothing to evaluate.
        if body.get("kind") == "body_mesh_converged":
            assert "target" not in body
            continue
        val = E.evaluate(body["target"], bp.variables)
        assert val > 0, f"{name}: composed body volume {val} is not positive"


@pytest.mark.parametrize("name", sorted(BASES))
def test_protruding_attachment_updates_z_extent(name):
    """(3) a pad standing on a mount raises the part; the z-extent assertion
    must grow with it or a correct build reads as a failure."""
    for seed in range(40):
        bp, meta = _compose(name, seed, natt=MAX_ATTACHMENTS)
        prot = [a for a in meta["attachments"]
                if a in ("bolt_boss", "locating_pin", "alignment_rib")]
        z_ext = [a for a in bp.assertions
                 if a.get("kind") == "bbox_extent" and a.get("axis") == "z"]
        if not (prot and z_ext):
            continue
        assert "max(" in z_ext[0]["target"], \
            f"{name}: z extent ignores protruding {prot}"
        return
    pytest.skip(f"{name}: no protruding draw with a z-extent assertion")


def test_meta_carries_audit_fields():
    bp, meta = _compose("mount_plate", 22, natt=2)
    for key in ("base_family", "attachments", "datum_strategy",
                "feature_sequence_hash", "feature_seq"):
        assert key in meta, f"missing audit field {key}"
    assert len(meta["feature_sequence_hash"]) == 16


def test_signature_separates_topologies():
    """Different attachment sets must hash differently; the diversity gate
    depends on it."""
    sigs = set()
    for seed in range(25):
        _bp, meta = _compose("mount_plate", seed, natt=MAX_ATTACHMENTS)
        sigs.add(meta["feature_sequence_hash"])
    assert len(sigs) > 3, "composition is not producing distinct topologies"


def test_attachments_stay_inside_their_land():
    """Placement must respect the declared free region — the composer's own
    containment contract, checked numerically."""
    for name in BASES:
        for seed in SEEDS:
            draft = None
            for s in range(seed, seed + 60):
                rng = random.Random(s)
                try:
                    draft = BASES[name](rng)
                    break
                except ValueError:
                    continue
            if draft is None:
                continue
            bp, meta = compose(draft, rng, n_attachments=MAX_ATTACHMENTS)
            v = bp.variables
            for i, _att in enumerate(meta["attachments"]):
                cx = v.get(f"att{i}_cx")
                cy = v.get(f"att{i}_cy")
                if cx is None:
                    continue
                inside = False
                for mount in draft["mounts"]:
                    land = mount["land"]
                    lw = E.evaluate(land["w"], v)
                    lh = E.evaluate(land["h"], v)
                    lcx = E.evaluate(land.get("cx", "0"), v)
                    lcy = E.evaluate(land.get("cy", "0"), v)
                    if (abs(cx - lcx) <= lw / 2 + 1e-6
                            and abs(cy - lcy) <= lh / 2 + 1e-6):
                        inside = True
                assert inside, f"{name}: attachment {i} at ({cx},{cy}) " \
                               f"outside every declared land"
