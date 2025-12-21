from app.intent.normalize import normalize
from app.intent.symbols import extract_numbers, extract_units

def encode(prompt: str) -> dict:
    """
    Encodes a prompt into a binary feature vector for XGBoost.
    """
    p = normalize(prompt)
    
    # Numeric extractions for feature presence checks
    nums = extract_numbers(p)
    units = extract_units(p)
    
    features = {
        "is_small": int(any(w in p for w in ["small", "tiny", "mini", "little"])),
        "is_large": int(any(w in p for w in ["large", "big", "huge", "massive", "giant"])),
        "is_long": int(any(w in p for w in ["long", "tall", "length"])),
        "is_thin": int(any(w in p for w in ["thin", "slender", "skinny", "narrow"])),
        "is_thick": int(any(w in p for w in ["thick", "fat", "wide"])),
        "has_dimensions": int(len(nums) > 0),
        "has_units": int(len(units) > 0),
        "has_x_separator": int("x" in p or "by" in p),
        "word_count": len(p.split()),
        # Semantic modifiers
        "is_strong": int("strong" in p),
        "is_heavy": int("heavy" in p)
    }
    
    return features

def flatten_features(features: dict) -> list[int]:
    """Helper to convert dict to list for model usage"""
    # Important: deterministic order
    keys = sorted(features.keys())
    return [features[k] for k in keys]
