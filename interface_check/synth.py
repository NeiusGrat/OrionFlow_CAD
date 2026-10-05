"""Synthetic robot assemblies with exact ground truth, and the seeded-error catalogue.

Three assemblies built in build123d from the knowledge base, so every hole,
bore and pattern is known exactly:

  motor_mount    NEMA 17 on a plate, plate bolted to a frame (M3 + M4)
  bearing_joint  608 bearing in a housing on a base, shaft and arm (+ URDF)
  chassis        chassis plate, two brackets, four standoffs, cover (+ BOM)

``MUTATIONS`` seeds exactly one error per variant, with the rule that must
catch it. ``build(assembly, mutation, out_dir)`` writes the STEP (and BOM /
URDF where the assembly has one) and returns their paths.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from build123d import Box, Compound, Cylinder, Location, Pos, export_step


def block(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def cyl(x, y, d, z0, z1):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def drill(solid, pts, d, z0, z1):
    for x, y in pts:
        solid = solid - cyl(x, y, d, z0, z1)
    return solid


def _label(shape, name):
    shape.label = name
    return shape


def _square(s):
    h = s / 2
    return [(-h, -h), (h, -h), (h, h), (-h, h)]


def _shift(pts, spec):
    if not spec:
        return pts
    k, dx = spec
    pts = list(pts)
    pts[k] = (pts[k][0] + dx, pts[k][1])
    return pts


def _drop(pts, k):
    return [p for i, p in enumerate(pts) if i != k] if k is not None else pts


# ------------------------------------------------------------------ motor_mount

def motor_mount(m: dict) -> tuple[list, dict]:
    sq = m.get("sq", 31.0)
    plate = block(-30, 30, -30, 30, 0, 5)
    if m.get("pilot_bore", 22.5):
        plate = drill(plate, [(0, 0)], m.get("pilot_bore", 22.5), -1, 6)
    plate = drill(plate, _shift(_square(sq), m.get("sq_shift")), 3.4, -1, 6)
    corners = _drop(_shift(_square(48), m.get("corner_shift")), m.get("corner_missing"))
    plate = drill(plate, corners, 4.5, -1, 6)

    motor = block(-21.15, 21.15, -21.15, 21.15, -40, 0)
    motor = drill(motor, _square(m.get("motor_sq", 31.0)), 2.5, -4.5, 0.5)
    motor = motor + cyl(0, 0, 22, 0, 2) + cyl(0, 0, 5, 2, 24)

    frame = block(-30, 30, -30, 30, -10, 0) - block(-21.5, 21.5, -21.5, 21.5, -11, 1)
    frame = drill(frame, _square(48), m.get("frame_tap", 3.3), -8, 0.5)

    parts = [_label(plate, "motor_plate"), _label(motor, "NEMA17_motor"), _label(frame, "frame_bracket")]
    return parts, {}


# ------------------------------------------------------------------ bearing_joint

def _pcd(pcd, n=4, start=45.0):
    return [(pcd / 2 * math.cos(math.radians(start + 360 * k / n)),
             pcd / 2 * math.sin(math.radians(start + 360 * k / n))) for k in range(n)]


def bearing_joint(m: dict) -> tuple[list, dict]:
    base = block(-40, 40, -40, 40, -6, 0)
    base = drill(base, _shift(_pcd(m.get("base_pcd", 40.0)), m.get("base_shift")), m.get("base_tap", 2.5), -7, 1)

    housing = block(-25, 25, -25, 25, 0, 12)
    housing = drill(housing, [(0, 0)], m.get("housing_bore", 22.0), 5, 13)
    housing = drill(housing, [(0, 0)], 16, -1, 5.0)
    housing = drill(housing, _pcd(40.0), 3.4, -1, 13)

    bearing = cyl(0, 0, 22, 5, 12) - cyl(0, 0, 8, 4, 13)
    shaft = cyl(0, 0, m.get("shaft", 8.0), 2, 30)
    arm = block(-10, 60, -10, 10, 14, 19) - cyl(0, 0, 8, 13, 20)

    parts = [_label(base, "base"), _label(housing, "housing"), _label(bearing, "608ZZ"),
             _label(shaft, "shaft_8mm"), _label(arm, "arm_link")]
    return parts, {}


#: link -> parts, and the joint between them (for the URDF the generator writes)
BEARING_LINKS = {"base_link": ["base", "housing", "608ZZ"], "arm_link": ["shaft_8mm", "arm_link"]}
DENSITY = {"base": 2700, "housing": 2700, "608ZZ": 7850, "shaft_8mm": 7850, "arm_link": 2700}
BEARING_BOM = """part_number,name,qty,rev,material
BJ-001,base,1,A,Aluminium 6061
BJ-002,housing,1,A,Aluminium 6061
608ZZ,608ZZ,1,,Steel
BJ-003,shaft_8mm,1,A,Steel
BJ-004,arm_link,1,A,Aluminium 6061
"""


def bearing_urdf(parts: list, m: dict) -> str:
    """URDF whose inertials are computed from the same solids (the clean truth)."""
    by = {p.label: p for p in parts}
    joint_xyz = [m.get("urdf_joint_dx", 0.0), 0.0, 0.012]
    links = []
    for link, names in BEARING_LINKS.items():
        mass, mom = 0.0, [0.0, 0.0, 0.0]
        for n in names:
            s = by[n]
            kg = s.volume * 1e-9 * DENSITY[n]
            c = s.center()
            mass += kg
            mom = [mom[0] + kg * c.X, mom[1] + kg * c.Y, mom[2] + kg * c.Z]
        com_mm = [v / mass for v in mom]
        if link == "arm_link":
            com_mm = [c - j * 1000 for c, j in zip(com_mm, joint_xyz)]
            mass *= m.get("urdf_arm_mass", 1.0)
            com_mm[0] += m.get("urdf_arm_com_dx", 0.0)
        links.append((link, mass, [v / 1000 for v in com_mm]))
    tilt = math.radians(m.get("urdf_axis_tilt_deg", 0.0))
    axis = [math.sin(tilt), 0.0, math.cos(tilt)]
    out = ['<robot name="bearing_joint">']
    for name, mass, com in links:
        out.append(f'  <link name="{name}"><inertial><origin xyz="{com[0]:.6f} {com[1]:.6f} {com[2]:.6f}"/>'
                   f'<mass value="{mass:.6f}"/><inertia ixx="1e-4" iyy="1e-4" izz="1e-4" ixy="0" ixz="0" iyz="0"/>'
                   '</inertial></link>')
    out.append(f'  <joint name="joint1" type="revolute"><parent link="base_link"/><child link="arm_link"/>'
               f'<origin xyz="{joint_xyz[0]} {joint_xyz[1]} {joint_xyz[2]}" rpy="0 0 0"/>'
               f'<axis xyz="{axis[0]:.6f} {axis[1]:.6f} {axis[2]:.6f}"/>'
               '<limit lower="-2" upper="2" effort="1" velocity="1"/></joint>')
    out.append("</robot>")
    return "\n".join(out)


# ------------------------------------------------------------------ chassis

STANDOFFS = [(-85, -40), (85, -40), (85, 40), (-85, 40)]


def chassis(m: dict) -> tuple[list, dict]:
    plate = block(-100, 100, -50, 50, 0, 5)
    feet = [(x + dx, 0) for x in (-60, 60) for dx in (-12, 12)]
    plate = drill(plate, _drop(feet, m.get("chassis_hole_missing")), 4.2, -1, 6)
    plate = drill(plate, STANDOFFS, 3.4, -1, 6)

    bracket = block(-20, 20, -15, 15, 5, 10) + block(-20, 20, 10, 15, 10, 35)
    bracket = drill(bracket, [(-12, 0), (12, 0)], m.get("bracket_clear", 5.5), 4, 11)

    standoff = cyl(0, 0, 6, 5, 40)
    standoff = drill(standoff, [(0, 0)], m.get("standoff_tap", 2.5), 4, 11)
    standoff = drill(standoff, [(0, 0)], m.get("standoff_tap", 2.5), 34, 41)

    cover = block(-100, 100, -50, 50, 40, 43)
    cover = drill(cover, _shift(STANDOFFS, m.get("cover_shift")), 3.4, 39, 44)

    brackets = [_label(bracket.moved(Location((x, 0, 0))), "side_bracket") for x in (-60, 60)]
    standoffs = [_label(standoff.moved(Location((x, y, 0))), "standoff_M3x35") for x, y in STANDOFFS]
    parts = [_label(plate, "chassis_plate"), _label(cover, "cover_plate"),
             _label(Compound(children=brackets), "brackets"), _label(Compound(children=standoffs), "posts")]
    return parts, {}


CHASSIS_BOM = [
    ["CH-001", "chassis_plate", "1", "A", "Aluminium 6061"],
    ["BR-002", "side_bracket", "2", "B", "Aluminium 6061"],
    ["HW-010", "standoff_M3x35", "4", "", "Brass"],
    ["CV-003", "cover_plate", "1", "A", "Acrylic"],
    ["HW-020", "M3x8 socket head screw", "8", "", "Steel"],
    ["HW-021", "M5x12 socket head screw", "4", "", "Steel"],
]


def chassis_bom(m: dict) -> str:
    rows = [list(r) for r in CHASSIS_BOM]
    for name, qty in (m.get("bom_qty") or {}).items():
        for r in rows:
            if r[1] == name:
                r[2] = str(qty)
    rows = [r for r in rows if r[1] not in (m.get("bom_drop") or [])]
    for old, new in (m.get("bom_rename") or {}).items():
        for r in rows:
            if r[1] == old:
                r[1], r[0] = new, (r[0] if m.get("bom_keep_pn", False) else "")
    for extra in m.get("bom_add") or []:
        rows.append(extra)
    return "\n".join(["part_number,name,qty,rev,material"] + [",".join(r) for r in rows]) + "\n"


def mesh_body(shape, tolerance: float = 0.5):
    """A solid rebuilt from its own triangles: what an STL-to-STEP conversion produces."""
    from build123d import Solid
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS

    from .report import tessellate

    v, t = tessellate(shape.wrapped, tolerance)
    sew = BRepBuilderAPI_Sewing(1e-4)
    for a, b, c in t:
        poly = BRepBuilderAPI_MakePolygon(*(gp_Pnt(*map(float, v[k])) for k in (a, b, c)), True)
        sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
    sew.Perform()
    return Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew.SewedShape())).Solid())


def mesh_bracket(m: dict) -> tuple[list, dict]:
    """A bolted plate pair plus a cast cover delivered as a mesh (scanned / STL-converted)."""
    from build123d import Sphere
    plate = drill(block(-30, 30, -30, 30, 0, 5), _square(40), 3.4, -1, 6)
    base = drill(block(-30, 30, -30, 30, -8, 0), _square(40), m.get("base_tap", 2.5), -6, 0.5)
    cover = mesh_body(Pos(0, 0, 5 + 12) * Sphere(12), m.get("mesh_tol", 0.3))
    return [_label(plate, "top_plate"), _label(base, "base_block"), _label(cover, "scanned_cover")], {}


ASSEMBLIES = {"motor_mount": motor_mount, "bearing_joint": bearing_joint, "chassis": chassis,
              "mesh_bracket": mesh_bracket}


# ------------------------------------------------------------------ mutations

@dataclass
class Mutation:
    id: str
    assembly: str
    params: dict
    expect: str | None                  # rule that must fire; None = must stay clean
    note: str = ""
    prev: dict | None = None            # revision test: previous revision's params
    expect_change: list[str] = field(default_factory=list)   # parts the diff must list as affected


MUTATIONS: list[Mutation] = [
    Mutation("mm_corner_1.0", "motor_mount", {"corner_shift": (0, 1.0)}, "HOLE_MISALIGNED", "plate corner hole moved 1.0 mm"),
    Mutation("mm_corner_0.5", "motor_mount", {"corner_shift": (2, 0.5)}, "HOLE_MISALIGNED", "plate corner hole moved 0.5 mm"),
    Mutation("mm_corner_2.0", "motor_mount", {"corner_shift": (1, -2.0)}, "HOLE_MISALIGNED", "plate corner hole moved 2.0 mm"),
    Mutation("mm_sq_hole_0.6", "motor_mount", {"sq_shift": (1, 0.6)}, "HOLE_MISALIGNED", "one motor hole moved 0.6 mm"),
    Mutation("mm_sq_33", "motor_mount", {"sq": 33.0}, "PATTERN_MISMATCH", "plate motor square 33 instead of 31"),
    Mutation("mm_pilot_20", "motor_mount", {"pilot_bore": 20.0}, "MOTOR_FLANGE", "pilot bore Ø20 under a Ø22 pilot"),
    Mutation("mm_pilot_none", "motor_mount", {"pilot_bore": None}, "MOTOR_FLANGE", "no pilot bore"),
    Mutation("mm_frame_tap_m3", "motor_mount", {"frame_tap": 2.5}, "FASTENER_SIZE_MISMATCH", "M4 clearance over M3 tap"),
    Mutation("mm_corner_missing", "motor_mount", {"corner_missing": 3}, "HOLE_MISSING", "plate corner hole deleted"),

    Mutation("bj_bore_+0.5", "bearing_joint", {"housing_bore": 22.5}, "BEARING_SEAT", "housing bore +0.5"),
    Mutation("bj_bore_+0.2", "bearing_joint", {"housing_bore": 22.2}, "BEARING_SEAT", "housing bore +0.2"),
    Mutation("bj_bore_-0.2", "bearing_joint", {"housing_bore": 21.8}, "BEARING_SEAT", "housing bore -0.2"),
    Mutation("bj_shaft_8.3", "bearing_joint", {"shaft": 8.3}, "BEARING_SEAT", "shaft Ø8.3 in an 8 mm bore"),
    Mutation("bj_pcd_43", "bearing_joint", {"base_pcd": 43.0}, "PATTERN_MISMATCH", "base bolt circle 43 vs 40"),
    Mutation("bj_pcd_44", "bearing_joint", {"base_pcd": 44.0}, "PATTERN_MISMATCH", "base bolt circle 44 vs 40"),
    Mutation("bj_tap_m4", "bearing_joint", {"base_tap": 3.3}, "FASTENER_SIZE_MISMATCH", "M3 clearance over M4 tap"),
    Mutation("bj_base_hole_1.5", "bearing_joint", {"base_shift": (0, 1.5)}, "HOLE_MISALIGNED", "base hole moved 1.5 mm"),
    Mutation("bj_urdf_mass", "bearing_joint", {"urdf_arm_mass": 1.10}, "URDF_MASS_DRIFT", "URDF arm mass +10%"),
    Mutation("bj_urdf_com", "bearing_joint", {"urdf_arm_com_dx": 5.0}, "URDF_COM_DRIFT", "URDF arm COM moved 5 mm"),
    Mutation("bj_urdf_axis", "bearing_joint", {"urdf_axis_tilt_deg": 2.0}, "JOINT_AXIS_DRIFT", "URDF joint axis 2° off"),
    Mutation("bj_urdf_origin", "bearing_joint", {"urdf_joint_dx": 0.003}, "JOINT_ORIGIN_DRIFT",
             "URDF joint origin 3 mm off the shaft axis"),

    Mutation("ch_bom_drop_bracket", "chassis", {"bom_drop": ["side_bracket"]}, "IN_CAD_NOT_BOM", "BOM row deleted"),
    Mutation("ch_bom_qty_standoff", "chassis", {"bom_qty": {"standoff_M3x35": 3}}, "BOM_QTY_MISMATCH", "standoff qty 3 vs 4"),
    Mutation("ch_bom_qty_bracket", "chassis", {"bom_qty": {"side_bracket": 1}}, "BOM_QTY_MISMATCH", "bracket qty 1 vs 2"),
    Mutation("ch_bom_add_camera", "chassis", {"bom_add": [["CM-009", "camera_mount", "1", "A", "PLA"]]},
             "IN_BOM_NOT_CAD", "BOM part missing from CAD"),
    Mutation("ch_bom_drop_standoff", "chassis", {"bom_drop": ["standoff_M3x35"]}, "IN_CAD_NOT_BOM", "hardware row deleted"),
    Mutation("ch_bom_typos", "chassis", {"bom_rename": {"chassis_plate": "Chasis Plate", "side_bracket": "side-brackett",
                                                       "cover_plate": "Cover plate"}}, None,
             "renamed BOM items must still match"),
    Mutation("ch_cover_hole_0.8", "chassis", {"cover_shift": (2, 0.8)}, "HOLE_MISALIGNED", "cover hole moved 0.8 mm"),
    Mutation("ch_chassis_hole_missing", "chassis", {"chassis_hole_missing": 2}, "HOLE_MISSING", "chassis tapped hole deleted"),
    Mutation("ch_bracket_m4", "chassis", {"bracket_clear": 4.5}, "FASTENER_SIZE_MISMATCH", "M4 clearance over M5 tap"),
    Mutation("ch_standoff_m4", "chassis", {"standoff_tap": 3.3}, "FASTENER_SIZE_MISMATCH", "M3 clearance over M4 tap"),

    Mutation("rev_plate_holes", "motor_mount", {"corner_shift": (0, 1.0)}, "HOLE_MISALIGNED",
             "Rev C moved a plate hole: diff lists the plate, its neighbours, a new finding",
             prev={}, expect_change=["motor_plate"]),
    Mutation("rev_base_pcd", "bearing_joint", {"base_pcd": 43.0}, "PATTERN_MISMATCH",
             "Rev C changed the base bolt circle", prev={}, expect_change=["base"]),
]


def build(assembly: str, params: dict, out_dir: str | Path, stem: str | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or assembly
    parts, _ = ASSEMBLIES[assembly](params)
    asm = _label(Compound(children=parts), assembly)
    step = out_dir / f"{stem}.step"
    export_step(asm, str(step).replace("\\", "/"))
    out = {"step": step}
    if assembly == "chassis":
        (out_dir / f"{stem}_bom.csv").write_text(chassis_bom(params))
        out["bom"] = out_dir / f"{stem}_bom.csv"
    if assembly == "bearing_joint":
        (out_dir / f"{stem}_bom.csv").write_text(BEARING_BOM)
        out["bom"] = out_dir / f"{stem}_bom.csv"
        flat = [p for p in parts]
        (out_dir / f"{stem}.urdf").write_text(bearing_urdf(flat, params))
        out["urdf"] = out_dir / f"{stem}.urdf"
        lines = [f"{link}: [{', '.join(assembly + '/' + n for n in names)}]" for link, names in BEARING_LINKS.items()]
        (out_dir / f"{stem}_urdf_map.yaml").write_text(chr(10).join(lines) + chr(10))
        out["urdf_map"] = out_dir / f"{stem}_urdf_map.yaml"
    return out
