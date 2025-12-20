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

    # height
    height_match = re.search(r"height\s*(\d+)", prompt)
    if height_match:
        params["height"] = float(height_match.group(1))

    # qualitative sizing
    if "small" in prompt:
        params.setdefault("radius", 10)
        params.setdefault("height", 20)

    if "large" in prompt:
        params.setdefault("radius", 50)
        params.setdefault("height", 100)

    return params
