def normalize(prompt: str) -> str:
    """
    Normalizes input text for consistent processing.
    """
    p = prompt.lower()
    p = p.replace("×", "x")
    p = p.replace("*", "x") 
    p = p.replace("millimeter", "mm")
    p = p.replace("centimeter", "cm")
    p = p.replace("meter", "m")
    p = p.replace("inch", "in")
    return p
