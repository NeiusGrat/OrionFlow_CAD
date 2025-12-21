import re
from app.intent.intent_schema import Intent

def extract_number_and_unit(prompt: str, keywords: list[str], default_val: float) -> tuple[float, str]:
    """
    Helper to extract a number near a keyword and its unit.
    Returns (value_in_mm, unit_string).
    """
    # 1. Try to find number + unit associated with keyword
    # e.g. "width 2cm", "20mm radius"
    
    # Combined regex is tricky, let's look for the keyword, then look for a number nearby
    # Simpler approach: Find the number associated with the keyword first (as before)
    
    val = default_val
    unit = "mm" # Default unit
    
    # Regex to find kw followed by number or number followed by kw
    # Capture number AND optional unit suffix
    # Units: mm, cm, m, in
    
    for kw in keywords:
        # Pattern: keyword ... number ... (unit)?
        # or number ... (unit)? ... keyword
        
        # specific pattern for "keyword ... value(unit)"
        # e.g. "radius 20cm"
        pattern_forward = rf"{kw}\s*(?:of|is)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in)?"
        match = re.search(pattern_forward, prompt, re.IGNORECASE)
        if match:
             raw_val = float(match.group(1))
             raw_unit = match.group(2)
             
             if raw_unit:
                 unit = raw_unit.lower()
                 if unit == "cm":
                     val = raw_val * 10
                 elif unit == "m":
                     val = raw_val * 1000
                 elif unit == "in":
                     val = raw_val * 25.4
                 else:
                     val = raw_val # mm
             else:
                 val = raw_val
                 unit = "mm"
             return val, unit

    return val, unit

def infer_parameters(intent: Intent, prompt: str) -> tuple[dict, dict]:
    prompt = prompt.lower()
    params = {}
    units = {} # Map param_name -> unit_str ("mm", "cm")
    
    # Generic inferred default helper
    def get(name, keywords, default):
        val, unit = extract_number_and_unit(prompt, keywords, default)
        params[name] = val
        units[name] = unit

    if intent.part_type == "box":
        # Check for explicit dimensions e.g. "10cm x 20cm x 5mm"
        # This is complex to normalize perfectly with mixed units in one regex
        # For now, let's stick to keyword extraction which is robust
        
        # However, we must handle the basic "10x10x10" case
        dim3_match = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm)?\s*[xX*]\s*(\d+(?:\.\d+)?)\s*(mm|cm)?\s*[xX*]\s*(\d+(?:\.\d+)?)\s*(mm|cm)?", prompt)
        
        if dim3_match:
             # Basic logic: if unit found, apply it. If not, use previous found unit or default mm?
             # Let's simplify: if 10x10x10, assume mm. If 10cm x 10cm, use cm.
             
             def parse_match_group(val_str, unit_str):
                 v = float(val_str)
                 u = unit_str.lower() if unit_str else "mm"
                 if u == "cm": v *= 10
                 return v, u

             l, lu = parse_match_group(dim3_match.group(1), dim3_match.group(2))
             w, wu = parse_match_group(dim3_match.group(3), dim3_match.group(4))
             h, hu = parse_match_group(dim3_match.group(5), dim3_match.group(6))
             
             params = {"length": l, "width": w, "height": h}
             units = {"length": lu, "width": wu, "height": hu}
        else:
            get("length", ["length", "long", "l"], 10.0)
            get("width", ["width", "wide", "w"], 10.0)
            get("height", ["height", "tall", "thick", "h"], 10.0)
            
    elif intent.part_type == "cylinder":
        get("radius", ["radius", "r", "rad"], 5.0)
        
        # Handle diameter special case
        # extract diameter first
        d_val, d_unit = extract_number_and_unit(prompt, ["diameter", "dia", "d"], -1.0)
        if d_val > 0:
            params["radius"] = d_val / 2.0
            units["radius"] = d_unit
            
        get("height", ["height", "tall", "length", "long", "h"], 10.0)

    elif intent.part_type == "shaft":
        get("radius", ["radius", "r"], 2.5)
        d_val, d_unit = extract_number_and_unit(prompt, ["diameter", "dia", "d"], -1.0)
        if d_val > 0:
             params["radius"] = d_val / 2.0
             units["radius"] = d_unit
             
        get("height", ["length", "long", "height"], 50.0)

    elif intent.part_type == "gear":
         # Gear teeth is unitless
         t_val, _ = extract_number_and_unit(prompt, ["teeth", "tooth", "num"], 20)
         params["teeth"] = int(t_val)
         units["teeth"] = ""
         
         get("radius", ["radius", "size"], 10.0)

    return params, units
