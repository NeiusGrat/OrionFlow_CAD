from app.intent.intent_schema import Intent

def parse_intent(prompt: str) -> Intent:
    prompt = prompt.lower()

    if any(w in prompt for w in ["cube", "box", "rectangle", "plate"]):
        return Intent(part_type="box")

    if any(w in prompt for w in ["cylinder", "rod", "pole", "tube"]):
        return Intent(part_type="cylinder")
        
    if "shaft" in prompt:
        return Intent(part_type="shaft")
    
    if "gear" in prompt:
         return Intent(part_type="gear")

    # Default fallback for now or raise Error
    # For strict mode we might want to raise, but let's default to cylinder if unsure 
    # to avoid crashing on random chat, OR strictly raise to force clarity.
    # The plan says "raise ValueError", so let's stick to the plan for strictness.
    raise ValueError("Unknown or unsupported part type in prompt.")
