"""OFL export — STEP and STL output from a Part."""
from pathlib import Path as _Path
from build123d import export_step as _export_step, export_stl as _export_stl
from .internal.errors import OFLError


def export(part, path):
    """Export *part* to STEP or STL based on file extension."""
    from .part import Part
    if not isinstance(part, Part):
        raise TypeError(f"Expected a Part, got {type(part).__name__}")
    p = _Path(path)
    ext = p.suffix.lower()
    if ext == ".step":
        _export_step(part._solid, str(p))
    elif ext == ".stl":
        _export_stl(part._solid, str(p))
    else:
        raise OFLError(f"Unsupported export format '{ext}' — use .step or .stl")
    if not p.exists():
        raise OFLError(f"Export failed: {path} was not created")
    if p.stat().st_size == 0:
        raise OFLError(f"Export failed: {path} is empty")
