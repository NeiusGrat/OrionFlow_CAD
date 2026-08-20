"""The authorship rule: which feature made which face.

``orion/topology_fc.py`` runs inside FreeCAD but imports nothing at module
scope, so the rule itself can be pinned here against a stand-in document rather
than only against a kernel. That matters because the rule is subtle and both of
the obvious readings of FreeCAD's element history are wrong:

* the **last** entry in the chain is the sketch the feature was drawn from;
* the **first** is whichever feature most recently touched the shape, which for
  a fillet is the fillet even on the flats it merely passed through.

The creator is the earliest feature at which the element is *already a face* —
before that its ancestor was an edge, which is to say the face did not exist.

The document modelled below is the one the rule was verified against in
FreeCAD 1.1.1: a 40x40x10 pad, a through bore, and a fillet on one vertical
edge. Attribution there is exact — bore wall to the bore, rounded corner to the
fillet, flats to the pad, nothing unattributed.
"""

import pytest

from orion import topology_fc as tf


# --------------------------------------------------------------------------- #
# a stand-in for the parts of FreeCAD's API the extractor touches
# --------------------------------------------------------------------------- #
class _V:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def negative(self):
        return _V(-self.x, -self.y, -self.z)


class _BoundBox:
    def __init__(self, box):
        self.XMin, self.YMin, self.ZMin, self.XMax, self.YMax, self.ZMax = box


class Plane:
    def __init__(self, position, axis):
        self.Position, self.Axis = position, axis


class Cylinder:
    def __init__(self, centre, axis, radius):
        self.Center, self.Axis, self.Radius = centre, axis, radius


class _Face:
    """Enough of ``Part.Face`` for the extractor: geometry plus a normal."""

    Orientation = "Forward"
    ParameterRange = (0.0, 1.0, 0.0, 1.0)

    def __init__(self, surface, area, centre, normal, box):
        self.Surface, self.Area = surface, area
        self.CenterOfMass = _V(*centre)
        self._normal = _V(*normal)
        self.BoundBox = _BoundBox(box)

    def normalAt(self, _u, _v):  # noqa: N802 - FreeCAD's spelling
        return self._normal


class _Feature:
    def __init__(self, name, type_id, element_map):
        self.Name, self.Label, self.TypeId = name, name, type_id
        self.Shape = type("S", (), {"ElementMap": element_map})()


class _Body:
    TypeId = "PartDesign::Body"
    Name = Label = "Body"

    def __init__(self, shape, group, history):
        self.Shape, self.Group, self._history = shape, group, history

    def getElementHistory(self, mapped):  # noqa: N802 - FreeCAD's spelling
        return self._history[mapped]


class _Doc:
    def __init__(self, body, features):
        self.Objects = [body] + features
        self._by_name = {f.Name: f for f in features}

    def getObject(self, name):  # noqa: N802 - FreeCAD's spelling
        return self._by_name.get(name)


UP = _V(0, 0, 1)


@pytest.fixture
def document():
    """Pad → through-bore → fillet, with the element history FreeCAD produces.

    Three faces are enough to state the rule: a flat the pad made, the bore wall
    the pocket made, and the rounded corner the fillet made. The fillet face's
    history runs back through the pocket *and* the pad, because it descends from
    an edge those features left behind — that is precisely the case a naive
    "deepest entry" or "first entry" reading gets wrong.
    """
    faces = [
        _Face(
            Plane(_V(0, 0, 10), UP),
            1518.03,
            (0, 0, 10),
            (0, 0, 1),
            (-20, -20, 10, 20, 20, 10),
        ),
        _Face(
            Cylinder(_V(0, 0, 10), UP, 5.0),
            314.16,
            (0, 0, 5),
            (-1, 0, 0),
            (-5, -5, 0, 5, 5, 10),
        ),
        _Face(
            Cylinder(_V(18, 18, 0), UP, 2.0),
            31.42,
            (19.4, 19.4, 5),
            (1, 1, 0),
            (18, 18, 0, 20, 20, 10),
        ),
    ]
    shape = type("S", (), {})()
    shape.Faces, shape.Edges, shape.Vertexes = faces, [], []
    shape.BoundBox = _BoundBox((-20, -20, 0, 20, 20, 10))
    shape.isNull = lambda: False
    shape.ElementReverseMap = {"Face1": "m1", "Face2": "m2", "Face3": "m3"}

    pad = _Feature("base_pad", "PartDesign::Pad", {"p1": "Face1", "p3": "Edge7"})
    bore = _Feature(
        "bore", "PartDesign::Pocket", {"b1": "Face1", "b2": "Face7", "b3": "Edge7"}
    )
    fillet = _Feature(
        "corner_round",
        "PartDesign::Fillet",
        {"m1": "Face1", "m2": "Face2", "m3": "Face3"},
    )

    history = {
        # a flat: a face at the pad already
        "m1": [(fillet, "m1", []), (bore, "b1", []), (pad, "p1", [])],
        # the bore wall: a face at the pocket, nothing at the pad
        "m2": [(fillet, "m2", []), (bore, "b2", [])],
        # the rounded corner: only an *edge* at the pocket and at the pad, so
        # neither made it — the fillet did.
        "m3": [(fillet, "m3", []), (bore, "b3", []), (pad, "p3", [])],
    }

    body = _Body(shape, [pad, bore, fillet], history)
    return _Doc(body, [pad, bore, fillet])


# --------------------------------------------------------------------------- #
# the rule
# --------------------------------------------------------------------------- #
def test_each_face_is_attributed_to_the_feature_that_made_it(document):
    record = tf.extract(document)

    assert record["attribution"] == "element_map"
    assert [f["feature"] for f in record["faces"]] == [
        "base_pad",
        "bore",
        "corner_round",
    ]
    assert record["counts"]["unattributed"] == 0


def test_a_dressup_owns_the_face_it_created_not_the_ones_it_passed_through(
    document,
):
    """The fillet touched all three faces; it authored exactly one.

    Reading the most recent entry in the history would credit it with all of
    them, which is the failure this rule exists to prevent — a UI would then
    highlight the whole part when asked to show a 2 mm corner break.
    """
    record = tf.extract(document)
    by_ref = {f["ref"]: f for f in record["faces"]}

    corner = by_ref["#o1.s1.f3"]
    assert corner["feature"] == "corner_round"
    # It still descends from them, and the lineage says so.
    assert corner["lineage"] == ["corner_round", "bore", "base_pad"]

    assert record["features"]["corner_round"]["faces"] == ["#o1.s1.f3"]
    assert len(record["features"]["base_pad"]["faces"]) == 1


def test_lineage_is_kept_apart_from_authorship(document):
    """Both are recorded because they answer different questions.

    "What made this?" is the creator. "What is this descended from?" is the
    lineage, and it is what a repair loop needs when the creator cannot be
    changed but an ancestor can.
    """
    record = tf.extract(document)
    wall = record["faces"][1]

    assert wall["feature"] == "bore"
    assert wall["lineage"] == ["corner_round", "bore"]


def test_a_face_a_feature_created_belongs_to_that_feature(document):
    """The other half of the rule, and the one that was missing.

    A feature's element map records what it *inherited*, not what it minted, so
    a face it created resolves nowhere in its own ancestry. Requiring a prior
    Face left every genuinely new face unattributed — bore walls, vent walls, a
    shell's inner skin. On the first enclosure measured that was 40 faces of
    121, and none of them could be clicked.
    """
    body = document.Objects[0]
    _pad, bore, _fillet = body.Group
    sketch = _Feature("s1", "Sketcher::SketchObject", {})

    # What a fresh cut really looks like: the operation that made the face and
    # the sketch it was cut with, and the element resolving at neither. Copied
    # from the enclosure — `vents:ABSENT -> s1:ABSENT`, 21 faces of it.
    body.Shape.ElementReverseMap["Face2"] = "new"
    body._history["new"] = [(bore, "new", []), (sketch, "new", [])]

    record = tf.extract(document)

    assert record["faces"][1]["feature"] == "bore"
    assert record["counts"]["unattributed"] == 0


def test_creation_never_overrides_a_real_inheritance(document):
    """The fallback is last, not first.

    A flat the pad made passes through the fillet untouched. If "newest in the
    chain" won, every face on the part would belong to the last operation.
    """
    record = tf.extract(document)

    assert record["faces"][0]["feature"] == "base_pad"
    assert record["faces"][2]["feature"] == "corner_round"


def test_an_element_map_that_is_missing_disables_attribution(document):
    """Older FreeCAD, or a shape that lost its map, must not be guessed at.

    A wrong feature id is worse than an absent one: the UI presents both with
    the same confidence, so a guess becomes a claim the user cannot check.
    """
    document.Objects[0].Shape.ElementReverseMap = {}

    record = tf.extract(document)

    assert record["attribution"] == "unavailable"
    assert all(f["feature"] is None for f in record["faces"])
    assert record["counts"]["unattributed"] == len(record["faces"])


def test_extraction_never_raises_on_a_document_with_no_body():
    """A build that succeeded must stay downloadable when this part fails."""
    empty = type("D", (), {"Objects": []})()

    record = tf.extract(empty)

    assert record["error"]
    assert record["faces"] == []


# --------------------------------------------------------------------------- #
# what gets written
# --------------------------------------------------------------------------- #
def test_a_surfaces_anchor_is_recorded_separately_from_its_centroid(document):
    """A quarter-cylinder's centroid is out on the rounded surface, not on the
    axis, so picking against the centroid would miss by the radius."""
    record = tf.extract(document)
    corner = record["faces"][2]

    assert corner["position"] == [18.0, 18.0, 0.0]  # on the axis
    assert corner["center"] == [19.4, 19.4, 5.0]  # on the surface
    assert corner["radius"] == 2.0


def test_stable_ordinals_are_numbered_per_feature(document):
    record = tf.extract(document)

    assert [f["stable"] for f in record["faces"]] == [
        "@base_pad.f0",
        "@bore.f0",
        "@corner_round.f0",
    ]


def test_orientation_is_not_applied_a_second_time(document):
    """``normalAt`` is already outward; flipping on ``Reversed`` points it in.

    This assertion used to say the opposite, on the reasoning that OCC stores a
    natural normal plus a flag the consumer must apply. True of raw OCC — but
    FreeCAD's ``Face.normalAt`` has applied it before we see the vector, so the
    extra flip inverted it.

    Settled by measurement, not by argument: stepping off each face along both
    candidates and asking ``Shape.isInside``, ``normalAt`` pointed outward on
    34 of 34 faces across four built parts, and the flipped vector on 13. Every
    ``Reversed`` face carried a normal pointing into the solid, which is most of
    a PartDesign pad.
    """
    document.Objects[0].Shape.Faces[0].Orientation = "Reversed"

    record = tf.extract(document)

    assert record["faces"][0]["normal"] == [0.0, 0.0, 1.0]


def test_coordinates_are_rounded_so_the_sidecar_is_byte_stable(document):
    """A digest over the sidecar is only meaningful if identical geometry
    serialises identically, and OCC returns full binary doubles."""
    document.Objects[0].Shape.Faces[0].CenterOfMass = _V(1 / 3, 2 / 3, 10.000000000001)

    record = tf.extract(document)

    assert record["faces"][0]["center"] == [0.333333, 0.666667, 10.0]


def test_the_record_says_whether_a_name_is_really_a_blueprint_feature(document):
    """reconstruct.py names objects after Blueprint ids, but FreeCAD sanitises
    and de-duplicates names — so this is stated rather than assumed."""
    graph = {"features": [{"id": "base_pad"}, {"id": "bore"}]}

    record = tf.extract(document, graph)

    assert record["features"]["base_pad"]["blueprint_feature"] is True
    assert record["features"]["corner_round"]["blueprint_feature"] is False


def test_topology_is_capped_rather_than_unbounded(document, monkeypatch):
    """The sidecar is served on the request path; one pathological model must
    not become a slow download for everybody."""
    monkeypatch.setattr(tf, "MAX_FACES", 2)

    record = tf.extract(document)

    assert len(record["faces"]) == 2
    assert "face" in record["truncated"]
