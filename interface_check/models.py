"""Records shared by every stage: parts, placed copies, features, findings."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np

from .version import ENGINE_VERSION

#: high    the assembly cannot be built as drawn (a bolt with no hole, a
#:         bearing that will not seat, a BOM that orders the wrong count).
#: medium  probably wrong, worth a look before release.
#: low     usually intentional (hardware left out of CAD), listed for completeness.
#: info    not a defect: an assumption, a match to confirm, a check skipped.
SEVERITIES = ("high", "medium", "low", "info")


@dataclass
class Part:
    """One part definition. Every placed copy of it is an :class:`Instance`."""

    part_id: str
    name: str
    shape: Any                      # TopoDS_Shape in part coordinates
    signature: dict = field(default_factory=dict)
    valid: bool = True
    problems: list[str] = field(default_factory=list)


@dataclass
class Instance:
    instance_id: str
    part_id: str
    path: str                       # "robot/arm/shoulder_bracket"
    shape: Any                      # TopoDS_Shape placed in assembly coordinates
    transform: np.ndarray           # 4x4, part -> assembly, millimetres
    loc: Any = None                 # TopLoc_Location of the same transform

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class Hole:
    """A concave cylinder that closes (>= ~300 degrees): a hole or a bore."""

    center: np.ndarray              # point on the axis, mid-depth
    axis: np.ndarray                # unit vector, canonical sign
    diameter: float
    depth: float

    def moved(self, T: np.ndarray) -> "Hole":
        return Hole(_pt(T, self.center), _dir(T, self.axis), self.diameter, self.depth)

    def span(self) -> tuple[np.ndarray, np.ndarray]:
        h = self.axis * self.depth / 2
        return self.center - h, self.center + h


@dataclass
class Boss:
    """A convex cylinder: a shaft, a pilot, the outside of a bearing."""

    center: np.ndarray
    axis: np.ndarray
    diameter: float
    length: float

    def moved(self, T: np.ndarray) -> "Boss":
        return Boss(_pt(T, self.center), _dir(T, self.axis), self.diameter, self.length)


@dataclass
class PlanarFace:
    point: np.ndarray               # centroid
    normal: np.ndarray              # outward
    area: float
    face: Any = None                # TopoDS_Face in part coordinates
    index: int = -1                 # position in the part's face enumeration (re-attaches cached faces)
    box: Optional[np.ndarray] = None    # AABB [x0, y0, z0, x1, y1, z1]

    def moved(self, T: np.ndarray, loc: Any = None) -> "PlanarFace":
        f = self.face.Moved(loc) if (self.face is not None and loc is not None) else self.face
        # A face normal has a side; only axis lines get a canonical sign.
        return PlanarFace(_pt(T, self.point), T[:3, :3] @ self.normal, self.area, f, self.index,
                          None if self.box is None else move_box(T, self.box))


@dataclass
class HolePattern:
    kind: str                       # "circle" | "rect" | "group"
    holes: list[Hole]
    axis: np.ndarray
    centroid: np.ndarray
    diameter: float                 # hole diameter
    pcd: Optional[float] = None     # bolt circle diameter
    a: Optional[float] = None       # rectangle sides, a <= b
    b: Optional[float] = None

    def describe(self) -> str:
        n = len(self.holes)
        if self.kind == "circle":
            return f"{n}x Ø{self.diameter:.2f} on PCD {self.pcd:.2f}"
        if self.kind == "rect":
            pcd = f" (PCD {self.pcd:.2f})" if self.pcd else ""
            return f"4x Ø{self.diameter:.2f} on {self.a:.2f} x {self.b:.2f}{pcd}"
        return f"{n}x Ø{self.diameter:.2f}"


@dataclass
class Features:
    holes: list[Hole] = field(default_factory=list)
    bosses: list[Boss] = field(default_factory=list)
    planes: list[PlanarFace] = field(default_factory=list)
    patterns: list[HolePattern] = field(default_factory=list)
    volume: float = 0.0             # mm^3
    area: float = 0.0               # mm^2
    com: np.ndarray = field(default_factory=lambda: np.zeros(3))
    inertia: np.ndarray = field(default_factory=lambda: np.zeros((3, 3)))   # mm^5, about COM
    bbox: tuple = ()                # sorted side lengths
    #: BREP: analytic faces, every rule applies. MESH: triangles saved as STEP;
    #: topology rules (holes, contact planes, interference) are skipped for it.
    geometry_type: str = "BREP"
    face_count: int = 0
    triangle_count: int = 0
    cached: bool = False

    def moved(self, T: np.ndarray, loc: Any = None) -> "Features":
        R = T[:3, :3]
        return Features(
            holes=[h.moved(T) for h in self.holes],
            bosses=[b.moved(T) for b in self.bosses],
            planes=[p.moved(T, loc) for p in self.planes],
            patterns=[_move_pattern(p, T) for p in self.patterns],
            volume=self.volume, area=self.area,
            com=_pt(T, self.com), inertia=R @ self.inertia @ R.T, bbox=self.bbox,
            geometry_type=self.geometry_type, face_count=self.face_count,
            triangle_count=self.triangle_count, cached=self.cached)

    @property
    def is_mesh(self) -> bool:
        return self.geometry_type == "MESH"


@dataclass
class Interface:
    """Two instances that touch, and the planes they touch on."""

    a: str
    b: str
    planes: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)   # (point, normal of A)
    distance: float = 0.0


@dataclass
class Finding:
    rule_id: str
    severity: str
    instances: list[str]            # instance paths, readable
    message: str
    measured: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    location: Optional[list[float]] = None
    parts: list[str] = field(default_factory=list)     # part names, stable across revisions
    assumptions: list[str] = field(default_factory=list)
    source: str = "geometry"        # geometry | bom | llm | urdf | revision
    change_status: Optional[str] = None                 # new | fixed | unchanged
    #: How the measured value was obtained, so every claim traces to a computation
    #: ("BRepExtrema distance", "cylinder axis offset", "BOM row count", ...).
    method: str = ""
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")
        if self.location is not None:
            self.location = [round(float(v), 3) for v in self.location]

    @property
    def fingerprint(self) -> str:
        """Same defect, same id, across two revisions (part names, not label ids)."""
        loc = "" if self.location is None else ",".join(f"{round(v):d}" for v in self.location)
        key = "|".join([self.rule_id, ",".join(sorted(self.parts or self.instances)), loc])
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint
        return _jsonable(d)

    def to_check(self) -> dict:
        """The stage-result shape: one failed check with its evidence."""
        sev = self.severity.upper()
        return _jsonable({
            "check_id": self.rule_id, "status": "WARNING" if self.severity in ("low", "info") else "FAIL",
            "severity": sev, "objects": self.instances or self.parts, "measurements": self.measured,
            "expected": self.expected,
            "evidence": [{"kind": "finding", "fingerprint": self.fingerprint, "source": self.source,
                          "method": self.method, "location_mm": self.location}],
            "reason": self.message, "engine_version": self.engine_version})


@dataclass
class Report:
    source: dict
    parts: list[dict] = field(default_factory=list)
    instances: list[dict] = field(default_factory=list)
    interfaces: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    fixed: list[Finding] = field(default_factory=list)     # previous revision's, now gone
    bom: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    llm_usage: dict = field(default_factory=dict)
    stages: list[dict] = field(default_factory=list)
    narrative: dict = field(default_factory=dict)      # AI explanation, every claim cites a fingerprint

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    def rules(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return out

    def to_dict(self) -> dict:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        fs = sorted(self.findings, key=lambda f: (order[f.severity], f.rule_id))
        return _jsonable({
            "source": self.source, "stats": self.stats,
            "summary": {s: self.count(s) for s in SEVERITIES} | {"rules": self.rules()},
            "assumptions": self.assumptions, "findings": [f.to_dict() for f in fs],
            "parts": self.parts, "instances": self.instances, "interfaces": self.interfaces,
            "changes": self.changes, "fixed": [f.to_dict() for f in self.fixed], "bom": self.bom,
            "llm_usage": self.llm_usage, "stages": self.stages, "narrative": self.narrative,
            "checks": [f.to_check() for f in fs], "engine_version": ENGINE_VERSION,
        })


# ------------------------------------------------------------------ helpers

def _pt(T: np.ndarray, p: np.ndarray) -> np.ndarray:
    return T[:3, :3] @ p + T[:3, 3]


def _dir(T: np.ndarray, d: np.ndarray) -> np.ndarray:
    return canon(T[:3, :3] @ d)


def canon(d: np.ndarray) -> np.ndarray:
    """One sign per axis line, so +Z and -Z holes compare equal."""
    d = np.asarray(d, dtype=float)
    d = d / (np.linalg.norm(d) or 1.0)
    i = int(np.argmax(np.abs(d)))
    return d if d[i] > 0 else -d


def move_box(T: np.ndarray, box: np.ndarray) -> np.ndarray:
    """AABB of the 8 moved corners of an AABB."""
    x0, y0, z0, x1, y1, z1 = box
    c = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    m = c @ T[:3, :3].T + T[:3, 3]
    return np.concatenate([m.min(axis=0), m.max(axis=0)])


def _move_pattern(p: HolePattern, T: np.ndarray) -> HolePattern:
    return HolePattern(p.kind, [h.moved(T) for h in p.holes], _dir(T, p.axis),
                       _pt(T, p.centroid), p.diameter, p.pcd, p.a, p.b)


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (float, np.floating)):
        return float(f"{float(o):.6g}")         # 6 significant digits: grams and metres both survive
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o
