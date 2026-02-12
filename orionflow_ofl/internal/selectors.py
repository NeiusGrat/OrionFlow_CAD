"""Face and bound selectors for OFL geometry operations."""

from .errors import GeometryError


def get_z_extent(solid):
    """Return (z_min, z_max) from the solid's bounding box."""
    bbox = solid.bounding_box()
    return bbox.min.Z, bbox.max.Z


def get_top_face_z(solid):
    """Return the Z coordinate of the top face centroid (highest Z)."""
    faces = solid.faces()
    if not faces:
        raise GeometryError("Solid has no faces")
    top = max(faces, key=lambda f: f.center().Z)
    return top.center().Z
