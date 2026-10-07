"""D1 Structure & identity: is the product tree what it claims to be?"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from .base import CheckConfig, Evidence, Finding, Quantity, check

_GENERIC = re.compile(
    r"^(solid|body|part|shape|component|compound|unnamed|untitled|open cascade step translator.*|"
    r"nauo\d*|product\d*|[0-9]+)[ _\-]?\d*$", re.I)
#: tokens that mark the left/right member of a mirrored pair
_SIDE = re.compile(r"(?<![A-Za-z])(L|R|LH|RH|left|right)(?![A-Za-z])", re.I)


def _side_neutral(name: str) -> str:
    return _SIDE.sub("*", name).strip().lower()


def _inst_ev(graph, part_id: str, limit: int = 4) -> list[Evidence]:
    return [Evidence(type="instance", id=i.id, label=i.name) for i in graph.instances if i.part_id == part_id][:limit]


@check("ST-TREE", "1.1.0", "structure", "Product tree sanity", requires=["parts"])
def st_tree(graph, cfg: CheckConfig) -> list[Finding]:
    """No assembly tree; unnamed parts; one name on different shapes; one shape under different names."""
    out: list[Finding] = []
    if graph.stats.flat:
        # Names in a flattened export are made up by the reader (<file>_bodyN), so judging them would only
        # report the reader's own naming. The one real defect is the missing tree itself.
        return [Finding(
            check_id="ST-TREE", check_version="1.1.0", domain="structure", severity="major",
            title="No assembly structure in the file",
            statement=f"{graph.source.name} is one shape holding {graph.stats.instances} solids: the export dropped the "
                      f"assembly tree and every part name. Parts are recognised by geometry only, so BOM rows and "
                      f"drawings cannot be matched by name, and sub-assemblies are lost.",
            measured=Quantity(value=0, unit="named parts", text=f"{graph.stats.instances} anonymous solids"),
            expected=Quantity(text="an assembly tree with part names", basis="STEP AP214/AP242 assembly export"),
            evidence=[Evidence(type="file", id=graph.source.name, label=graph.source.name, sha256=graph.source.sha256)],
            recommendation="Re-export from CAD as an assembly (STEP AP214 or AP242 with product structure), not as one body.",
            key="flat-file")]
    for p in graph.parts:
        if not p.name.strip() or p.name == p.id or _GENERIC.match(p.name.strip()):
            out.append(Finding(
                check_id="ST-TREE", check_version="1.1.0", domain="structure", severity="minor",
                title="Part has no meaningful name",
                statement=f"Part {p.id} is named \"{p.name}\", which identifies nothing. It cannot be matched to a BOM row or a drawing.",
                measured=Quantity(text=p.name or "(empty)"), expected=Quantity(text="a part name or number", basis="naming rule"),
                evidence=[Evidence(type="part", id=p.id, label=p.name)] + _inst_ev(graph, p.id),
                recommendation="Name the part in CAD with its part number before exporting.", key=f"unnamed:{p.id}"))

    by_name: dict[str, list] = defaultdict(list)
    for p in graph.parts:
        by_name[p.name.strip().lower()].append(p)
    for name, ps in by_name.items():
        if len(ps) > 1 and len({p.hash for p in ps}) > 1:
            out.append(Finding(
                check_id="ST-TREE", check_version="1.1.0", domain="structure", severity="major",
                title="One name, different shapes",
                statement=f"{len({p.hash for p in ps})} geometrically different parts are all named \"{ps[0].name}\". "
                          f"A BOM line or a drawing for that name cannot say which one it means.",
                measured=Quantity(value=len({p.hash for p in ps}), unit="shapes"), expected=Quantity(value=1, unit="shapes", basis="one name per shape"),
                evidence=[Evidence(type="part", id=p.id, label=f"{p.name} ({p.volume / 1000:.2f} cm³)") for p in ps],
                recommendation="Give each variant its own part number (e.g. a revision or size suffix).", key=f"samename:{name}"))

    by_hash: dict[str, list] = defaultdict(list)
    for p in graph.parts:
        by_hash[p.hash].append(p)
    for h, ps in by_hash.items():
        names = sorted({p.name for p in ps})
        if len(names) < 2:
            continue
        if len({_side_neutral(n) for n in names}) == 1:
            continue                       # FLAP_L / FLAP_R: a mirrored pair has the same volume, area and envelope
        out.append(Finding(
            check_id="ST-TREE", check_version="1.1.0", domain="structure", severity="minor",
            title="Same shape, different names",
            statement=f"{', '.join(names)} have the same volume ({ps[0].volume / 1000:.3f} cm³), area and envelope. "
                      f"Either one part was saved twice under two names, or two parts that should share a BOM line do not.",
            measured=Quantity(value=len(names), unit="names"), expected=Quantity(value=1, unit="names", basis="one name per shape"),
            evidence=[Evidence(type="part", id=p.id, label=p.name) for p in ps],
            recommendation="Confirm whether these are the same part; if so, use one part number.", key=f"samehash:{h}"))
    return out


def _world_com(graph, inst) -> np.ndarray:
    T = np.asarray(inst.transform, float)
    c = np.asarray(graph.part(inst.part_id).com, float)
    return T[:3, :3] @ c + T[:3, 3]


@check("ST-DUP-BODY", "1.1.0", "structure", "Duplicate bodies at one placement", requires=["instances"])
def st_dup_body(graph, cfg: CheckConfig) -> list[Finding]:
    """Two copies of the same shape in the same place: a copy-paste error that doubles the BOM count.

    "Same place" is the same centre of mass in the assembly frame, which holds whatever frame each part
    was defined in (a flattened file's bodies carry their position in their geometry, not a transform).
    """
    tol = cfg.get("dup_body_tol_mm")
    hash_of = {p.id: p.hash for p in graph.parts}
    groups: dict[tuple, list] = defaultdict(list)
    for i in graph.instances:
        key = (hash_of[i.part_id], tuple(np.round(_world_com(graph, i) / max(tol * 10, 1e-6)).astype(int)))
        groups[key].append(i)
    out = []
    for (h, *_), insts in groups.items():
        if len(insts) < 2:
            continue
        a, b = _world_com(graph, insts[0]), _world_com(graph, insts[1])
        out.append(Finding(
            check_id="ST-DUP-BODY", check_version="1.1.0", domain="structure", severity="major",
            title="Duplicate body at the same placement",
            statement=f"{len(insts)} copies of {insts[0].name} occupy exactly the same place. The assembly counts "
                      f"{len(insts)} where one is visible, so the BOM quantity derived from CAD is wrong.",
            measured=Quantity(value=round(float(np.linalg.norm(a - b)), 6), unit="mm", text="centre-of-mass offset"),
            expected=Quantity(min=tol, unit="mm", basis=cfg.basis("dup_body_tol_mm")),
            evidence=[Evidence(type="instance", id=i.id, label=i.path) for i in insts],
            recommendation="Delete the extra copies in CAD.", key="dup:" + ",".join(sorted(i.id for i in insts))))
    return out


@check("ST-UNITS", "1.0.0", "structure", "Unit sanity", requires=["instances"])
def st_units(graph, cfg: CheckConfig) -> list[Finding]:
    """Absurd sizes: an assembly a millimetre across, or a part far too small to be real."""
    lo = np.min([i.bbox.min for i in graph.instances], axis=0)
    hi = np.max([i.bbox.max for i in graph.instances], axis=0)
    size = float(np.max(hi - lo))
    out = []
    if size < 1.0 or size > 100_000.0:
        out.append(Finding(
            check_id="ST-UNITS", check_version="1.0.0", domain="structure", severity="critical",
            title="Assembly size is implausible",
            statement=f"The whole assembly is {size:.4g} mm across. A robot assembly is not this size: the file was probably "
                      f"exported in the wrong unit (metres or inches read as millimetres).",
            measured=Quantity(value=round(size, 4), unit="mm"), expected=Quantity(min=1.0, max=100000.0, unit="mm", basis="plausible robot size"),
            evidence=[Evidence(type="file", id=graph.source.name, label=graph.source.name, sha256=graph.source.sha256)],
            recommendation="Check the export unit; re-export in millimetres.", key="assembly-size"))
    tiny = cfg.get("unit_tiny_mm")
    for p in graph.parts:
        dim = float(max(np.subtract(p.bbox.max, p.bbox.min)))
        if dim < tiny:
            out.append(Finding(
                check_id="ST-UNITS", check_version="1.0.0", domain="structure", severity="major",
                title="Part is far too small to be real",
                statement=f"{p.name} is {dim:.4g} mm across, in an assembly {size:.0f} mm across. It is a stray body, "
                          f"or it was modelled in a different unit.",
                measured=Quantity(value=round(dim, 6), unit="mm"), expected=Quantity(min=tiny, unit="mm", basis=cfg.basis("unit_tiny_mm")),
                evidence=[Evidence(type="part", id=p.id, label=p.name)] + _inst_ev(graph, p.id),
                recommendation="Delete the stray body or fix its unit.", key=f"tiny:{p.id}"))
    return out
