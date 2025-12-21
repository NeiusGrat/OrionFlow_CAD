from app.intent.intent_schema import Intent
import random

def validate(params: dict, intent: Intent):
    """
    Validates parameters based on the intent.
    Raises ValueError if parameters are invalid (e.g., negative dimensions).
    """
    if intent.part_type == "box":
        if params.get("length", 0) <= 0: raise ValueError("Box length must be positive.")
        if params.get("width", 0) <= 0: raise ValueError("Box width must be positive.")
        if params.get("height", 0) <= 0: raise ValueError("Box height must be positive.")
        
        # Engineering logic check: aspect ratio shouldn't be too insane for a 'box'
        # e.g., length shouldn't be 1000x height unless it's a plate?
        # Let's keep it loose but helpful
        if params["height"] > 10 * params["length"]:
             # Warning only? Or fail? Let's just pass for now but commented out.
             # raise ValueError("Height is disproportionately large for length")
             pass

    elif intent.part_type in ["cylinder", "shaft"]:
        if params.get("radius", 0) <= 0: raise ValueError(f"{intent.part_type.capitalize()} radius must be positive.")
        if params.get("height", 0) <= 0: raise ValueError(f"{intent.part_type.capitalize()} height must be positive.")

def stress_test(part_cls, params: dict):
    """
    Randomly perturbs parameters to ensure geometry stability.
    """
    test_params = params.copy()
    # Jiggle by 10%
    for k in test_params:
        if isinstance(test_params[k], (int, float)):
             test_params[k] *= 1.1
             
    # Try build
    try:
        part_cls(test_params).build()
    except Exception as e:
        raise RuntimeError(f"Part failed stress test: {e}")

