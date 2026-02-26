"""Convert STL to GLB (binary glTF) for the Three.js viewer."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def stl_to_glb(stl_path: str, glb_path: str = None) -> Optional[str]:
    """Convert STL file to GLB. Returns output path or None on failure."""
    try:
        import trimesh
    except ImportError:
        logger.warning("trimesh not installed, skipping GLB conversion")
        return None

    if glb_path is None:
        glb_path = stl_path.replace('.stl', '.glb')

    try:
        mesh = trimesh.load(stl_path)
        mesh.export(glb_path, file_type='glb')
        if os.path.exists(glb_path) and os.path.getsize(glb_path) > 100:
            return glb_path
        return None
    except Exception as e:
        logger.error(f"STL→GLB conversion failed: {e}")
        return None
