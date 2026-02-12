"""OFL error hierarchy — fail fast with clear messages."""


class OFLError(Exception):
    """Base error for all OFL operations."""


class GeometryError(OFLError):
    """Raised when a geometry operation fails or produces invalid output."""
