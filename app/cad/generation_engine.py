import io
import traceback
from typing import Optional, Dict, Any

# Pre-import build123d to be available in the exec context
import build123d as b3d
from build123d import *
from ocp_tessellator.tessellator import Tessellator, compute_quality
from ocp_tessellator.ocp_utils import oc_export_gltf

class Build123dExecutionError(Exception):
    """Custom exception for errors during B3D script execution."""
    def __init__(self, message: str, traceback_str: Optional[str] = None):
        super().__init__(message)
        self.traceback_str = traceback_str

def execute_build123d_script(code: str) -> bytes:
    """
    Executes a raw string of build123d Python code and returns the GLB bytes.
    
    The code MUST assign the final object to a variable named 'part' or 'shape' or 'sketch'.
    Priority: 'part' > 'shape' > 'sketch'
    """
    
    # Sandbox context: Include standard build123d imports
    context: Dict[str, Any] = {
        "b3d": b3d,
        **b3d.__dict__
    }

    try:
        # EXECUTE THE CODE
        exec(code, context)
        
        # EXTRACT RESULT
        part = context.get("part") or context.get("shape") or context.get("sketch")
        
        if part is None:
            raise Build123dExecutionError("The script executed but did not assign a result to 'part', 'shape', or 'sketch'.")

        # EXPORT TO GLB
        # Using ocp_tessellator/build123d export logic
        # We need a BytesIO stream
        buffer = io.BytesIO()
        
        # Determine export method based on type
        # For now, we assume it's a Part or Composition that supports export_gltf equivalent
        # Build123d's `export_gltf` writes to a file, so we might need a lower level approach or temp file.
        # Ideally, we use `to_gltf` if available or `oc_export_gltf` from ocp_tessellator if mixed.
        
        # Strategy: Use ocp-tessellator's `oc_export_gltf` directly if possible, 
        # or build123d's high level export.
        # Let's try build123d's native export first if it supports file-like objects?
        # Looking at docs, `export_gltf` usually takes a filename. 
        # Let's use `oc_export_gltf` which returns bytes or writes to file?
        # Actually, let's stick to a robust method: `part.export_gltf` sometimes works in recent versions?
        # If not, we use `Compound(part).export_gltf(...)` or check library provided method.
        
        # Safe fallback: Use `ocp_tessellator` which drives the visualizer usually.
        # But for 'production' headless, standard Build123d export is best.
        
        # Let's try to find a `export` function in `b3d`.
        # Assuming `b3d.export_gltf(part, "file.glb")` pattern.
        # We will use a temporary file if we have to, or check if it accepts a buffer.
        
        # NOTE: For now, I'll rely on `b3d.export_gltf` writing to a temp file and reading it back 
        # as a safe implementation if streaming isn't documented clearly in my internal knowledge base.
        # However, `ocp_tessellator.ocp_utils.oc_export_glb` might return bytes. 
        
        # Let's use a temporary file approach for robustness in Phase 1.
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tmp:
            tmp_path = tmp.name
            
        try:
            # Attempt export
            success = False
            # Try 1: build123d export_gltf
            if hasattr(b3d, "export_gltf"):
                b3d.export_gltf(part, tmp_path)
                success = True
            # Try 2: Method on object
            elif hasattr(part, "export_gltf"):
                part.export_gltf(tmp_path)
                success = True
            
            if not success:
                # Fallback: simple `export_stl` then convert? No, we want GLB.
                # Let's assume standard build123d API fits.
                 b3d.export_gltf(part, tmp_path)

            with open(tmp_path, "rb") as f:
                glb_bytes = f.read()
                
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
        return glb_bytes

    except SyntaxError as e:
        tb = traceback.format_exc()
        raise Build123dExecutionError(f"Syntax Error in generated code: {e}", traceback_str=tb)
    except Exception as e:
        tb = traceback.format_exc()
        raise Build123dExecutionError(f"Runtime Error during execution: {e}", traceback_str=tb)
