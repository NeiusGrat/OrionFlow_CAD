import re
from app.intent.intent_schema import Intent

def extract_number(prompt: str, keywords: list[str], default: float) -> float:
    """Helper to extract a number near a keyword"""
    for kw in keywords:
        # Regex to find kw followed by number or number followed by kw
        # e.g. "radius 10", "10mm radius", "radius of 10"
        pattern = rf"{kw}\s*(?:of|is)?\s*[:=]?\s*(\d+(?:\.\d+)?)"
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            return float(match.group(1))
            
    return default

def infer_parameters(intent: Intent, prompt: str) -> dict:
    prompt = prompt.lower()
    params = {}
    
    if intent.part_type == "box":
        # Defaults
        params["length"] = 10.0
        params["width"] = 10.0
        params["height"] = 10.0
        
        # Try to extract specific dims
        # Logic: look for "10x20x30" pattern first
        dim3_match = re.search(r"(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)", prompt)
        dim2_match = re.search(r"(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)", prompt)
        
        if dim3_match:
            params["length"] = float(dim3_match.group(1))
            params["width"] = float(dim3_match.group(2))
            params["height"] = float(dim3_match.group(3))
        elif dim2_match:
            params["length"] = float(dim2_match.group(1))
            params["width"] = float(dim2_match.group(2))
            # Keep default height or infer from thickness
            params["height"] = extract_number(prompt, ["height", "tall", "thick", "h"], 10.0)
        else:
            # Look for individual keywords
            params["length"] = extract_number(prompt, ["length", "long", "l"], 10.0)
            params["width"] = extract_number(prompt, ["width", "wide", "w"], 10.0)
            params["height"] = extract_number(prompt, ["height", "tall", "thick", "h"], 10.0)
            
    elif intent.part_type == "cylinder":
        params["radius"] = extract_number(prompt, ["radius", "r", "rad"], 5.0)
        # Handle diameter input
        dia = extract_number(prompt, ["diameter", "dia", "d"], -1.0)
        if dia > 0:
            params["radius"] = dia / 2.0
            
        params["height"] = extract_number(prompt, ["height", "tall", "length", "long", "h"], 10.0)

    elif intent.part_type == "shaft":
        # Shaft is basically a cylinder but maybe different defaults
        params["radius"] = extract_number(prompt, ["radius", "r"], 2.5)
        dia = extract_number(prompt, ["diameter", "dia", "d"], -1.0)
        if dia > 0:
            params["radius"] = dia / 2.0
        params["height"] = extract_number(prompt, ["length", "long", "height"], 50.0)

    elif intent.part_type == "gear":
         # Placeholder for gear
         params["teeth"] = int(extract_number(prompt, ["teeth", "tooth", "num"], 20))
         params["radius"] = extract_number(prompt, ["radius", "size"], 10.0)

    return params
