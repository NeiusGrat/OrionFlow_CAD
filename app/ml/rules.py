import re

def rule_based_extract(prompt: str) -> dict:
    """
    Deterministic parameter extraction.
    Returns only what it confidently finds.
    """
    prompt = prompt.lower()
    params = {}

    # radius / diameter
    radius_match = re.search(r"radius\s*(\d+)", prompt)
    diameter_match = re.search(r"diameter\s*(\d+)", prompt)
    
    if radius_match:
        params["radius"] = float(radius_match.group(1))
    elif diameter_match:
        params["radius"] = float(diameter_match.group(1)) / 2

    # height (also depth/thickness for plates)
    height_match = re.search(r"(height|depth|thickness)\s*(\d+)", prompt)
    if height_match:
        params["height"] = float(height_match.group(2))

    # length
    length_match = re.search(r"length\s*(\d+)", prompt)
    if length_match:
        params["length"] = float(length_match.group(1))
    
    # width
    width_match = re.search(r"width\s*(\d+)", prompt)
    if width_match:
        params["width"] = float(width_match.group(1))

    # qualitative sizing
    if "small" in prompt:
        params.setdefault("radius", 10)
        params.setdefault("height", 20)
        params.setdefault("length", 20)
        params.setdefault("width", 20)

    if "large" in prompt:
        params.setdefault("radius", 50)
        params.setdefault("height", 100)
        params.setdefault("length", 100)
        params.setdefault("width", 100)

    return params

def infer_part_type(prompt: str) -> str:
    """
    Infer the intended part type from the prompt.
    Defaults to 'cylinder'.
    """
    prompt = prompt.lower()
    
    if any(w in prompt for w in ["box", "cube", "plate", "rectangular"]):
        return "box"
    
    if any(w in prompt for w in ["shaft", "rod", "pole"]):
        return "shaft"
        
    return "cylinder"
