from app.intent.intent_schema import Intent

def validate(params: dict, intent: Intent):
    """
    Validates parameters based on the intent.
    Raises ValueError if parameters are invalid (e.g., negative dimensions).
    """
    if intent.part_type == "box":
        if params.get("length", 0) <= 0:
            raise ValueError("Box length must be positive.")
        if params.get("width", 0) <= 0:
            raise ValueError("Box width must be positive.")
        if params.get("height", 0) <= 0:
            raise ValueError("Box height must be positive.")

    elif intent.part_type in ["cylinder", "shaft"]:
        if params.get("radius", 0) <= 0:
             raise ValueError(f"{intent.part_type.capitalize()} radius must be positive.")
        if params.get("height", 0) <= 0:
             raise ValueError(f"{intent.part_type.capitalize()} height must be positive.")
