"""Face and bound selectors for OFL geometry operations."""

from .errors import GeometryError


def get_z_extent(solid):
    """Return (z_min, z_max) from the solid's bounding box."""
    bbox = solid.bounding_box()
    return bbox.min.Z, bbox.max.Z


def get_axis_extent(solid, axis):
    """Return (min, max) of the solid's bounding box along "x", "y", or "z"."""
    bbox = solid.bounding_box()
    return {
        "x": (bbox.min.X, bbox.max.X),
        "y": (bbox.min.Y, bbox.max.Y),
        "z": (bbox.min.Z, bbox.max.Z),
    }[axis]


def get_top_face_z(solid):
    """Return the Z coordinate of the top face centroid (highest Z)."""
    faces = solid.faces()
    if not faces:
        raise GeometryError("Solid has no faces")
    top = max(faces, key=lambda f: f.center().Z)
    return top.center().Z
