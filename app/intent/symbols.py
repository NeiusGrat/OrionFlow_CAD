import re

def extract_numbers(prompt: str) -> list[float]:
    """
    Extracts all numeric values from the prompt.
    """
    # Matches integers and floats like 10, 10.5, .5
    matches = re.findall(r"[-+]?\d*\.\d+|\d+", prompt)
    return [float(m) for m in matches if m.strip() not in ["", ".", "-", "+"]]

def extract_units(prompt: str) -> list[str]:
    """
    Extracts known units from the prompt.
    """
    units = ["mm", "cm", "m", "in", "ft"]
    # Simple lexical check usually sufficient after normalization
    found = [u for u in units if u in prompt.split()] 
    # Use split() to avoid matching "mm" inside "dummy" if strict check needed, 
    # but "20mm" is common. Let's use simplified regex or basic check.
    # For now, regex boundary check is safer.
    found_units = []
    for u in units:
        if re.search(rf"\b{u}\b", prompt) or re.search(rf"\d+{u}", prompt):
           found_units.append(u)
    return found_units
