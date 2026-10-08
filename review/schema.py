"""The Model Graph: one canonical, versioned description of a product revision.

Every check reads only from this. It is built once per revision by the ingest
job (:mod:`review.ingest`) and persisted as JSON, so a check can be re-run, a
finding can be re-traced and two revisions can be compared without touching
the original files again.

Units: millimetres, mm^2, mm^3, degrees. Transforms are 4x4 row-major,
part -> assembly coordinates, translation in millimetres.

Later milestones fill the lists that are empty here (features, contacts,
joints, bom_rows, documents, components); bumping ``SCHEMA_VERSION`` is
required whenever the meaning of an existing field changes.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.3"   # 1.1: features + contacts; 1.2: joints, threads, overlaps, clearances

FileKind = Literal["step", "bom", "pdf", "urdf", "mjcf", "mesh", "other"]


class SourceFile(BaseModel):
    name: str
    kind: FileKind
    sha256: str
    size: int


class Bbox(BaseModel):
    min: list[float]                 # [x, y, z] mm, in the frame it belongs to
    max: list[float]

    @property
    def size(self) -> list[float]:
        return [b - a for a, b in zip(self.min, self.max)]


class Part(BaseModel):
    """A part definition. Placed copies of it are :class:`Instance` s."""

    id: str                          # "p001", stable within a revision
    name: str
    hash: str                        # geometric signature hash: survives renames, changes with shape
    volume: float                    # mm^3
    area: float                      # mm^2
    bbox: Bbox                       # in part coordinates
    com: list[float]                 # mm, part coordinates
    #: inertia about the COM for unit density (mm^5), part frame; times density (kg/mm^3) gives kg mm^2
    inertia: Optional[list[list[float]]] = None
    valid: bool = True
    problems: list[str] = Field(default_factory=list)
    face_count: int = 0
    triangle_count: int = 0
    geometry_type: Literal["BREP", "MESH"] = "BREP"
    material: Optional[str] = None   # filled from BOM / Library (M5)
    process: Optional[str] = None
    mass: Optional[float] = None     # kg, only once a density is known
    mass_source: Optional[str] = None  # how the mass was obtained (BOM material, an engineer's override)
    features: list[str] = Field(default_factory=list)   # feature ids
    plane_count: int = 0


class Instance(BaseModel):
    """One placed copy of a part, addressed everywhere by ``id``.

    The viewer GLB uses the same id as its node name, so a pick in 3D, a row
    in the tree and a finding's evidence all resolve to the same thing.
    """

    id: str                          # "i0001"
    part_id: str
    path: str                        # "YUBI Gripper Assy/CASE" (unique within the revision)
    name: str
    transform: list[list[float]]     # 4x4, part -> assembly, mm
    parent: Optional[str] = None     # instance id of the enclosing sub-assembly, if any
    bbox: Bbox                       # in assembly coordinates


class TreeNode(BaseModel):
    """Product tree for display: assemblies hold children, leaves hold an instance."""

    key: str                         # path
    name: str
    instance: Optional[str] = None   # leaf -> instance id
    children: list["TreeNode"] = Field(default_factory=list)


class Stats(BaseModel):
    parts: int
    instances: int
    assemblies: int
    max_depth: int
    triangles: int = 0
    features: int = 0
    contacts: int = 0
    flat: bool = False               # STEP had no assembly structure (one body per solid)


class ModelGraph(BaseModel):
    schema_version: str = SCHEMA_VERSION
    revision_id: str
    units: Literal["mm"] = "mm"
    source: SourceFile               # the STEP the geometry came from
    files: list[SourceFile] = Field(default_factory=list)
    stats: Stats
    parts: list[Part]
    instances: list[Instance]
    tree: TreeNode
    ingest_notes: list[str] = Field(default_factory=list)  # repairs made while reading (reported, not hidden)
    # ---- filled by later milestones -------------------------------------------
    #: hole | cylinder | pattern, part frame (mm); see review.geometry for the fields
    features: list[dict] = Field(default_factory=list)
    #: touching pairs: {id, a, b, type, kinds, min_distance, point, planes, fits, coaxial_holes}
    contacts: list[dict] = Field(default_factory=list)
    #: non-touching pairs closer than 1 mm: {a, b, min_distance, point}
    clearances: list[dict] = Field(default_factory=list)
    joints: list[dict] = Field(default_factory=list)       # M7 / M8
    bom_rows: list[dict] = Field(default_factory=list)     # M5
    documents: list[dict] = Field(default_factory=list)    # M9
    components: list[dict] = Field(default_factory=list)   # M4 / M10

    @property
    def sim(self) -> Optional[dict]:
        """The sim-model document (URDF/MJCF read and compared), if the revision has one."""
        return next((d for d in self.documents if d.get("kind") == "sim"), None)

    @property
    def motion(self) -> Optional[dict]:
        """Sweeps of confirmed joints (review/motion.py), if any joint has been swept with its current spec."""
        d = next((d for d in self.documents if d.get("kind") == "motion"), None)
        return d if d and d.get("sweeps") else None

    def part(self, pid: str) -> Part:
        return next(p for p in self.parts if p.id == pid)

    def instance(self, iid: str) -> Instance:
        return next(i for i in self.instances if i.id == iid)


TreeNode.model_rebuild()
