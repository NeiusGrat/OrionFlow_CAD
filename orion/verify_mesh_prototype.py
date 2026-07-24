"""Numerical verification prototype for the 32 hard records (FreeCAD python).

Two independent methods, neither of which reads OCC's analytic B-rep volume:

  A. MESH-SAMPLED 3D VOLUME (divergence theorem on a tessellation).
     tessellate(deflection) -> (verts, facets); V = (1/6) sum n.(v0.(v1xv2)),
     facet winding is OCC-outward. As deflection -> 0, V_mesh -> V_true.
     Works for ANY solid (extrude, loft, sweep). Evaluated across several
     tessellation densities to measure convergence.

  B. GREEN'S-THEOREM PROFILE AREA (for the B-spline EXTRUDES).
     A B-spline extrude has V = A_profile * height. The profile area is the
     planar line integral A = (1/2) oint (x dy - y dx) over the outer wire
     minus the inner wires. Discretised at rising point counts it converges;
     with exact Bezier-segment Gauss quadrature it is EXACT (the integrand is
     a polynomial), which is the Tier-1 upgrade path. Here we run the
     discretised form and watch it converge to prove the area is independently
     computable without trusting OCC's Face.Area.

Ground truth for convergence is OCC shape.Volume — the number the corpus
already stores. Agreement of an INDEPENDENT method with it is the evidence
that upgrades a record out of single-source measured_only.
"""
import json
import FreeCAD as App

FCSTD = "E:/OrionFLow_CAD/freecad/data/fcstd/%s.FCStd"
DEFLECTIONS = [0.8, 0.4, 0.2, 0.1, 0.05, 0.02]
GREEN_NPTS = [200, 800, 3200, 12800]

hard = json.load(open("E:/OrionFLow_CAD/data/forge/_hard_records.json"))


def body_shape(doc):
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    for b in bodies:
        if b.Shape and not b.Shape.isNull() and b.Shape.Volume > 1e-9:
            return b.Shape
    solids = [o.Shape for o in doc.Objects
              if getattr(o, "Shape", None) is not None
              and not o.Shape.isNull() and o.Shape.Volume > 1e-9]
    return max(solids, key=lambda s: s.Volume) if solids else None


def mesh_volume(shape, deflection):
    verts, facets = shape.tessellate(deflection)
    v6 = 0.0
    for a, b, c in facets:
        p, q, r = verts[a], verts[b], verts[c]
        # signed six-times-volume of tetra (origin, p, q, r)
        v6 += (p.x * (q.y * r.z - q.z * r.y)
               - p.y * (q.x * r.z - q.z * r.x)
               + p.z * (q.x * r.y - q.y * r.x))
    return abs(v6) / 6.0, len(facets)


def green_area(wire, npts):
    """Discretised (1/2) oint (x dy - y dx) over a planar wire (XY)."""
    pts = wire.discretize(Number=npts)
    a2 = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i].x, pts[i].y
        x1, y1 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
        a2 += x0 * y1 - x1 * y0
    return abs(a2) / 2.0


def profile_area_green(shape, npts):
    """Sum signed areas of the bottom face's wires (outer - holes)."""
    zmin = shape.BoundBox.ZMin
    base = None
    for f in shape.Faces:
        if abs(f.Surface.Axis.z) > 0.999 and abs(f.CenterOfMass.z - zmin) < 1e-3:
            base = f
            break
    if base is None:
        return None
    outer = green_area(base.OuterWire, npts)
    holes = sum(green_area(w, npts) for w in base.Wires
                if not w.isSame(base.OuterWire))
    return outer - holes


results = []
for h in hard:
    tag = h["tag"]
    try:
        doc = App.openDocument(FCSTD % tag)
    except Exception as e:  # noqa: BLE001
        results.append({"tag": tag, "error": "open: %s" % str(e)[:60]})
        continue
    shp = body_shape(doc)
    if shp is None:
        results.append({"tag": tag, "error": "no solid"})
        App.closeDocument(doc.Name)
        continue
    Vocc = shp.Volume
    mesh = []
    for d in DEFLECTIONS:
        try:
            vm, nf = mesh_volume(shp, d)
            mesh.append({"defl": d, "V": vm, "facets": nf,
                         "rel_err": abs(vm - Vocc) / Vocc})
        except Exception as e:  # noqa: BLE001
            mesh.append({"defl": d, "error": str(e)[:50]})
    rec = {"tag": tag, "class": h["class"], "V_occ": Vocc, "mesh": mesh}
    if h["class"] == "bspline_extrude":
        # height = z extent (single-Pad masters); multi-feature ones still
        # extrude the base profile through the full part, so A*Zext is the
        # additive-region check, not exact for pocketed parts -> report area
        # convergence only.
        greens = []
        for n in GREEN_NPTS:
            try:
                a = profile_area_green(shp, n)
                greens.append({"npts": n, "area": a})
            except Exception as e:  # noqa: BLE001
                greens.append({"npts": n, "error": str(e)[:50]})
        rec["green_area"] = greens
    results.append(rec)
    App.closeDocument(doc.Name)

json.dump(results, open("E:/OrionFLow_CAD/data/forge/_mesh_convergence.json", "w"),
          indent=1)
print("evaluated", len(results), "records")
ok = [r for r in results if "mesh" in r]
finest = [r["mesh"][-1]["rel_err"] for r in ok
          if "rel_err" in r["mesh"][-1]]
if finest:
    finest.sort()
    print("finest-mesh rel_err: min %.2e  median %.2e  max %.2e"
          % (finest[0], finest[len(finest) // 2], finest[-1]))
