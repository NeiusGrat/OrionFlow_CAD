from app.services.generation_service import GenerationService

def test_unsupported_expert_prompt():
    prompt = "Create a symmetric bracket with filleted edges"

    intent = GenerationService.decompose_prompt(prompt)

    assert "symmetry" in intent.unsupported_intent
    assert "fillet" in intent.unsupported_intent
    assert "extrude" not in intent.unsupported_intent

def test_supported_prompt_decomposition():
    prompt = "Create a rectangle plate 100x50 with a hole"
    
    intent = GenerationService.decompose_prompt(prompt)
    
    # Sketch
    assert "base_profile" in intent.sketch_intent
    assert "circle" in intent.sketch_intent
    
    # Features
    assert "extrude" in intent.feature_intent
    
    # Unsupported
    assert not intent.unsupported_intent

def test_expert_constraints():
    prompt = "Horizontal and vertical alignment with distance constraints"
    
    intent = GenerationService.decompose_prompt(prompt)
    
    assert "orientation" in intent.constraint_intent
    assert "dimension" in intent.constraint_intent
