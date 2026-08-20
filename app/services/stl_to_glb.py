"""Convert STL to GLB (binary glTF) for the Three.js viewer.

The GLB is written with an explicit PBR material rather than left bare. The
studio viewport overrides the material anyway (it swaps in its own instances to
drive hover and selection state), so for a long time this did not appear to
matter — but the GLB is also the file a user downloads and the file any
non-studio consumer opens, and glTF's default for a mesh with no material is
untextured flat white. A part therefore looked like an engineering component
inside the app and like a blank blob everywhere else.

The values are the same machined-aluminium surface the viewer uses; see
``orionflow-ui/src/lib/cadAppearance.ts``, which is the definition both sides
follow.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: Machined aluminium, as authored for the viewport (sRGB hex).
#: Kept in sync with ``CAD_SURFACE`` in ``lib/cadAppearance.ts``.
CAD_BASE_COLOR_SRGB = "#c2c7cf"
CAD_METALLIC = 0.72
CAD_ROUGHNESS = 0.29


def _srgb_to_linear(c: float) -> float:
    """One sRGB channel (0..1) to linear.

    glTF's ``baseColorFactor`` is defined in **linear** space, while the hex the
    UI is authored in is sRGB. Writing the sRGB value straight through would
    publish a part noticeably lighter than the viewport's, which is the kind of
    mismatch this whole change exists to remove.
    """
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _base_color_factor() -> list:
    h = CAD_BASE_COLOR_SRGB.lstrip("#")
    srgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return [round(_srgb_to_linear(c), 6) for c in srgb] + [1.0]


def stl_to_glb(stl_path: str, glb_path: str = None) -> Optional[str]:
    """Convert STL file to GLB. Returns output path or None on failure."""
    try:
        import trimesh
    except ImportError:
        logger.warning("trimesh not installed, skipping GLB conversion")
        return None

    if glb_path is None:
        glb_path = stl_path.replace(".stl", ".glb")

    try:
        mesh = trimesh.load(stl_path)

        # An STL carries no normals worth trusting and no material at all.
        # Attaching one here is what makes the exported file self-describing.
        try:
            from trimesh.visual.material import PBRMaterial  # noqa: PLC0415

            material = PBRMaterial(
                name="OrionFlow CAD Surface",
                baseColorFactor=_base_color_factor(),
                metallicFactor=CAD_METALLIC,
                roughnessFactor=CAD_ROUGHNESS,
                doubleSided=False,
            )
            for geom in (
                mesh.geometry.values() if hasattr(mesh, "geometry") else [mesh]
            ):
                if hasattr(geom, "visual"):
                    geom.visual = trimesh.visual.TextureVisuals(material=material)
        except Exception as exc:  # noqa: BLE001
            # A GLB without the material is still a correct GLB. Losing the
            # geometry because the appearance could not be attached would trade
            # a cosmetic problem for a functional one.
            logger.warning("could not attach PBR material to GLB: %s", exc)

        mesh.export(glb_path, file_type="glb")
        if os.path.exists(glb_path) and os.path.getsize(glb_path) > 100:
            return glb_path
        return None
    except Exception as e:
        logger.error(f"STL→GLB conversion failed: {e}")
        return None
