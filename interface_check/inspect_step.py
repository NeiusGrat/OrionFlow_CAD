"""Complexity gate: what a STEP file will cost, read before any geometry is built.

The text is streamed once in fixed-size chunks (memory does not grow with the
file) and entity types are counted. That is enough to decide, before an
expensive B-rep transfer, whether the file is valid STEP at all, how big the
assembly is, how much of it is a triangulated mesh, and which worker tier can
hold it — or that no tier should try.

File size alone is a poor predictor: a 20 MB file of B-spline surfaces can
cost more than a 100 MB file of flat triangles whose rules are skipped. So the
estimate is built from the counts that drive cost — B-rep faces that will be
analysed, faces that will only be loaded, solids, instances — and the
coefficients live in ``COST_MODEL`` so measured worker runs can retune them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHUNK = 4 * 1024 * 1024
_ENTITY = re.compile(rb"#\d+\s*=\s*([A-Z][A-Z0-9_]*)\s*\(")
_LOOP = re.compile(rb"=\s*EDGE_LOOP\s*\(\s*'[^']*'\s*,\s*\(([^)]*)\)")
_POLY = re.compile(rb"=\s*POLY_LOOP\s*\(\s*'[^']*'\s*,\s*\(([^)]*)\)")
_SCHEMA = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'")

COUNTED = {
    b"ADVANCED_FACE": "faces", b"FACE_SURFACE": "faces", b"POLY_LOOP": "poly_loops",
    b"EDGE_CURVE": "edges", b"VERTEX_POINT": "vertices", b"EDGE_LOOP": "edge_loops",
    b"MANIFOLD_SOLID_BREP": "solids", b"BREP_WITH_VOIDS": "solids", b"FACETED_BREP": "faceted_solids",
    b"CLOSED_SHELL": "shells", b"OPEN_SHELL": "shells", b"SHELL_BASED_SURFACE_MODEL": "surface_models",
    b"NEXT_ASSEMBLY_USAGE_OCCURRENCE": "instances", b"PRODUCT": "products",
    b"PLANE": "planes", b"CYLINDRICAL_SURFACE": "cylinders", b"CONICAL_SURFACE": "analytic",
    b"SPHERICAL_SURFACE": "analytic", b"TOROIDAL_SURFACE": "analytic",
    b"B_SPLINE_SURFACE_WITH_KNOTS": "bsplines", b"RATIONAL_B_SPLINE_SURFACE": "bsplines",
    b"TRIANGULATED_FACE": "tessellated", b"TRIANGULATED_SURFACE_SET": "tessellated",
    b"COMPLEX_TRIANGULATED_SURFACE_SET": "tessellated", b"TESSELLATED_SHELL": "tessellated",
}

#: memory_gb ~ base + per-file-MB + per analysed face + per loaded-only face.
#: Seeded from one 111 MB / 89k-face run (peak 1.23 GB through ingest);
#: retune from ``worker_runs`` peak memory once real jobs exist.
COST_MODEL = {"base_gb": 0.5, "per_file_mb_gb": 0.012, "per_brep_face_gb": 4.0e-5,
              "per_mesh_face_gb": 1.2e-5, "per_instance_gb": 2.0e-3, "safety": 1.6}

#: worker tiers: (name, memory GB, cpu). A job goes to the smallest whose
#: memory covers the estimate.
TIERS = (("SMALL", 8, 4), ("MEDIUM", 16, 8), ("LARGE", 32, 16), ("EXTREME", 64, 32))


@dataclass
class Complexity:
    file_size: int = 0
    schema: str = ""
    valid_header: bool = False
    terminated: bool = False
    counts: dict = field(default_factory=dict)
    triangle_loops: int = 0
    mesh_ratio: float = 0.0              # share of face loops that are triangles (or poly loops)
    estimated_memory_gb: float = 0.0
    complexity_score: float = 0.0
    tier: str = "SMALL"
    problems: list[str] = field(default_factory=list)

    def get(self, k: str) -> int:
        return int(self.counts.get(k, 0))

    @property
    def face_count(self) -> int:
        return self.get("faces") + self.get("poly_loops")

    @property
    def part_count(self) -> int:
        return max(self.get("products"), 1)

    @property
    def solid_count(self) -> int:
        return self.get("solids") + self.get("faceted_solids")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(face_count=self.face_count, part_count=self.part_count, solid_count=self.solid_count)
        return d


def inspect(path: str | Path) -> Complexity:
    path = Path(path)
    c = Complexity(file_size=path.stat().st_size)
    counts: dict[str, int] = {}
    tri = 0
    with open(path, "rb") as fh:
        head = fh.read(4096)
        c.valid_header = head.lstrip().startswith(b"ISO-10303-21")
        m = _SCHEMA.search(head)
        c.schema = m.group(1).decode(errors="replace") if m else ""
        fh.seek(0)
        tail, last = b"", b""
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            last = (last + chunk)[-512:]
            buf = tail + chunk
            cut = buf.rfind(b";")            # count only complete entities; carry the rest
            if cut < 0:
                tail = buf[-CHUNK:]
                continue
            body, tail = buf[:cut + 1], buf[cut + 1:]
            for em in _ENTITY.finditer(body):
                k = COUNTED.get(em.group(1))
                if k:
                    counts[k] = counts.get(k, 0) + 1
            for lm in _LOOP.finditer(body):
                tri += lm.group(1).count(b"#") == 3
            for pm in _POLY.finditer(body):
                tri += pm.group(1).count(b"#") == 3
        c.terminated = b"END-ISO-10303-21" in last
    c.counts = counts
    c.triangle_loops = tri
    loops = counts.get("edge_loops", 0) + counts.get("poly_loops", 0)
    c.mesh_ratio = round(tri / loops, 4) if loops else 0.0
    _estimate(c)
    if not c.valid_header:
        c.problems.append("INVALID_STEP: no ISO-10303-21 header")
    elif not c.terminated:
        c.problems.append("CORRUPTED_FILE: no END-ISO-10303-21 trailer (truncated upload?)")
    elif c.face_count == 0 and not counts.get("tessellated"):
        c.problems.append("INVALID_STEP: no faces or solids in the file")
    return c


def _estimate(c: Complexity) -> None:
    m = COST_MODEL
    faces = c.face_count + c.get("tessellated")
    mesh_faces = int(faces * c.mesh_ratio) + c.get("tessellated")
    brep_faces = max(faces - mesh_faces, 0)
    gb = (m["base_gb"] + m["per_file_mb_gb"] * c.file_size / 2**20 + m["per_brep_face_gb"] * brep_faces
          + m["per_mesh_face_gb"] * mesh_faces + m["per_instance_gb"] * c.get("instances")) * m["safety"]
    c.estimated_memory_gb = round(gb, 2)
    # Score: the same quantity normalised to the SMALL tier, so 1.0 = fills an 8 GB worker.
    c.complexity_score = round(gb / TIERS[0][1], 3)
    c.tier = next((name for name, mem, _ in TIERS if gb <= mem * 0.8), "REJECT")


def tier_resources(tier: str) -> tuple[int, int]:
    """(memory GB, cpu) of a tier."""
    for name, mem, cpu in TIERS:
        if name == tier:
            return mem, cpu
    raise KeyError(tier)


def next_tier(tier: str) -> str | None:
    names = [t[0] for t in TIERS]
    i = names.index(tier)
    return names[i + 1] if i + 1 < len(names) else None
