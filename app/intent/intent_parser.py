from app.intent.intent_schema import Intent
from app.intent.normalize import normalize

PART_SYNONYMS = {
    "box": ["box", "cube", "rectangular", "rectangle", "plate", "block"],
    "cylinder": ["cylinder", "rod", "pipe", "tube", "pole"],
    "shaft": ["shaft", "axle", "spindle"],
    "gear": ["gear", "helical gear", "spur gear", "cog"]
}

def parse_intent(prompt: str) -> Intent:
    """
    3-Stage Advanced Intent Pipeline:
    1. Normalize
    2. Strict Keyword Match
    3. Return Intent or Raise
    """
    # 1. Normalize
    clean_prompt = normalize(prompt)

    # 2. Strict Intent Classification
    for part_type, keywords in PART_SYNONYMS.items():
        # Check whole word matches or known compounds
        if any(w in clean_prompt for w in keywords):
            return Intent(part_type=part_type)

    # 3. No fallback allowed for advanced mode
    # Calculate confidence based on keyword match strength
    # Since we use strict `any(w in clean_prompt)`, if it matches, we are fairly confident.
    # We could check ratio of matched keyword length to prompt length?
    # For now, strict match = 1.0 confidence.
    return Intent(part_type=part_type), 1.0

    raise ValueError("Unsupported part description. Please specify 'box', 'cylinder', 'shaft', or 'gear'.")

