"""
Validators for LLM-generated build123d code.
Pre-execution validation to catch common issues early.
"""
import re
from typing import List


def validate_build123d_code(code: str) -> List[str]:
    """
    Pre-execution validation of generated code.
    Returns list of warnings (not errors—LLM might surprise us).
    
    Args:
        code: Generated Python code string
        
    Returns:
        List of warning messages
    """
    warnings = []
    
    # Check for result assignment
    if not re.search(r'\b(part|shape|sketch)\s*=', code):
        warnings.append("Code may not assign result to 'part', 'shape', or 'sketch'")
    
    # Check for forbidden imports
    if re.search(r'\bimport\b', code):
        warnings.append("Code contains 'import' statement (will fail in sandbox)")
    
    # Check for filesystem access
    forbidden_funcs = ['open', 'read', 'write', 'os.', 'sys.', 'subprocess']
    for func in forbidden_funcs:
        if func in code:
            warnings.append(f"Code contains '{func}' (will fail in sandbox)")
    
    # Check for eval/exec
    if 'eval(' in code or 'exec(' in code:
        warnings.append("Code contains 'eval' or 'exec' (will fail in sandbox)")
    
    # Check for __import__
    if '__import__' in code:
        warnings.append("Code contains '__import__' (will fail in sandbox)")
    
    return warnings


def validate_result_object(obj: any) -> bool:
    """
    Validate that the result object is a valid build123d object.
    
    Args:
        obj: Object to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not hasattr(obj, "__class__"):
        return False
    
    # Check if it's a build123d object
    obj_type = str(type(obj))
    return "build123d" in obj_type or "Part" in obj_type or "Sketch" in obj_type
