"""Semantic PMI from a STEP AP242 file: the model's own dimensions and tolerances.

An AP242 file with *semantic* PMI stores every dimension, tolerance and datum
as data, not as drawn text. Read with OpenCASCADE's GD&T reader, that is an
answer key for the drawing reader: the drawing and the model were authored
from the same definition, so every characteristic on one should be on the
other. NIST publishes its MBE PMI test cases exactly this way, which is what
makes their accuracy demonstrable rather than claimed.

Units: OpenCASCADE converts lengths to millimetres; angles are degrees.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: OpenCASCADE dimension types -> our characteristic types
_DIM_TYPE = {
    "Location_LinearDistance": "Linear", "Location_LinearDistance_FromCenterToOuter": "Linear",
    "Location_LinearDistance_FromCenterToInner": "Linear", "Location_LinearDistance_FromOuterToCenter": "Linear",
    "Location_LinearDistance_FromOuterToOuter": "Linear", "Location_LinearDistance_FromOuterToInner": "Linear",
    "Location_LinearDistance_FromInnerToCenter": "Linear", "Location_LinearDistance_FromInnerToOuter": "Linear",
    "Location_LinearDistance_FromInnerToInner": "Linear", "Location_Angular": "Angle", "Location_Oriented": "Linear",
    "Location_WithPath": "Linear", "Size_CurveLength": "Linear", "Size_Diameter": "Diameter",
    "Size_SphericalDiameter": "Diameter", "Size_Radius": "Radius", "Size_SphericalRadius": "Radius",
    "Size_ToroidalMinorDiameter": "Diameter", "Size_ToroidalMajorDiameter": "Diameter",
    "Size_ToroidalMinorRadius": "Radius", "Size_ToroidalMajorRadius": "Radius",
    "Size_ToroidalHighMajorDiameter": "Diameter", "Size_ToroidalLowMajorDiameter": "Diameter",
    "Size_ToroidalHighMajorRadius": "Radius", "Size_ToroidalLowMajorRadius": "Radius",
    "Size_Thickness": "Linear", "Size_Angular": "Angle", "Size_WithPath": "Linear",
    "CommonLabel": "Linear", "DimensionPresentation": "Linear",
}
#: OpenCASCADE geometric tolerance types -> drawcheck's characteristic names
_GT_TYPE = {
    "Angularity": "angularity", "CircularRunout": "circular_runout", "CircularityOrRoundness": "circularity",
    "Coaxiality": "concentricity", "Concentricity": "concentricity", "Cylindricity": "cylindricity",
    "Flatness": "flatness", "Parallelism": "parallelism", "Perpendicularity": "perpendicularity",
    "Position": "position", "ProfileOfLine": "profile_line", "ProfileOfSurface": "profile_surface",
    "Straightness": "straightness", "Symmetry": "symmetry", "TotalRunout": "total_runout",
}


@dataclass
class PmiItem:
    kind: str                       # dimension | gdt | datum
    type: str                       # Linear | Diameter | Radius | Angle | <gdt characteristic> | datum
    nominal: float | None = None
    lower: float | None = None      # deviation (mm / deg) for dimensions
    upper: float | None = None
    tolerance: float | None = None  # zone for GD&T
    diameter_zone: bool = False
    material: str | None = None     # M | L
    datums: list[str] = field(default_factory=list)
    count: int = 1
    label: str = ""                 # the datum letter, or the PMI's own name
    raw_type: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _name(enum_value) -> str:
    n = getattr(enum_value, "name", str(enum_value))
    return n.split("_", 2)[-1] if n.startswith("XCAFDimTolObjects_") else n


def _attrs(lab):
    from OCP.TDF import TDF_AttributeIterator

    it = TDF_AttributeIterator(lab)
    while it.More():
        yield it.Value()
        it.Next()


def _typed(lab, cls_name: str):
    return next((a for a in _attrs(lab) if type(a).__name__ == cls_name), None)


def _round(v: float | None, n: int = 6) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), n)


def read_pmi(path: str | Path) -> dict:
    """{'dimensions': [...], 'gdt': [...], 'datums': [...], 'source': name} — empty lists when the
    file carries no semantic PMI (an AP203 or AP214 geometry-only file)."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("pmi"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"{Path(path).name}: not a readable STEP file")
    reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())

    out = {"source": Path(path).name, "dimensions": [], "gdt": [], "datums": []}
    dims = TDF_LabelSequence()
    tool.GetDimensionLabels(dims)
    for i in range(1, dims.Length() + 1):
        a = _typed(dims.Value(i), "XCAFDoc_Dimension")
        if a is None:
            continue
        o = a.GetObject()
        raw = _name(o.GetType())
        typ = _DIM_TYPE.get(raw, "Linear")
        if raw in ("CommonLabel", "DimensionPresentation"):
            continue                       # presentation-only, no semantic value
        val = o.GetValue()
        if typ == "Angle":
            val = math.degrees(val) if val < 2 * math.pi + 1e-9 else val
        lo = hi = None
        if o.IsDimWithPlusMinusTolerance():
            lo, hi = o.GetLowerTolValue(), o.GetUpperTolValue()
            if typ == "Angle":
                lo, hi = math.degrees(lo), math.degrees(hi)
        elif o.IsDimWithRange():
            lo, hi = o.GetLowerBound() - val, o.GetUpperBound() - val
        out["dimensions"].append(PmiItem("dimension", typ, _round(val), _round(lo), _round(hi), raw_type=raw).to_dict())

    gts = TDF_LabelSequence()
    tool.GetGeomToleranceLabels(gts)
    for i in range(1, gts.Length() + 1):
        lab = gts.Value(i)
        a = _typed(lab, "XCAFDoc_GeomTolerance")
        if a is None:
            continue
        o = a.GetObject()
        raw = _name(o.GetType())
        mat = _name(o.GetMaterialRequirementModifier())
        datums = []
        seq = TDF_LabelSequence()
        try:
            XCAFDoc_DocumentTool.DimTolTool_s(doc.Main()).GetDatumWithObjectOfTolerLabels_s(lab, seq)
        except Exception:  # noqa: BLE001 - datums are best effort
            pass
        for j in range(1, seq.Length() + 1):
            d = _typed(seq.Value(j), "XCAFDoc_Datum")
            if d is not None:
                try:
                    datums.append(d.GetObject().GetName().ToCString())
                except Exception:  # noqa: BLE001
                    pass
        out["gdt"].append(PmiItem(
            "gdt", _GT_TYPE.get(raw, raw.lower()), tolerance=_round(o.GetValue()),
            diameter_zone=_name(o.GetTypeOfValue()) == "Diameter",
            material={"M": "M", "L": "L"}.get(mat[:1]) if mat not in ("None", "") else None,
            datums=datums, raw_type=raw).to_dict())

    dts = TDF_LabelSequence()
    tool.GetDatumLabels(dts)
    letters = set()
    for i in range(1, dts.Length() + 1):
        d = _typed(dts.Value(i), "XCAFDoc_Datum")
        if d is None:
            continue
        try:
            letters.add(d.GetObject().GetName().ToCString())
        except Exception:  # noqa: BLE001
            pass
    out["datums"] = sorted(x for x in letters if x)
    return out
