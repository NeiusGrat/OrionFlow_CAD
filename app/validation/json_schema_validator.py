"""
JSON Schema Validator - Enforce strict JSON output from LLM.

==============================================================================
PURPOSE: Strict JSON Enforcement (Step 6 Requirement)
==============================================================================

This module validates LLM outputs against strict JSON schemas to:
1. Detect and log schema violations
2. Enable debugging of LLM JSON issues
3. Provide clear validation error messages for training data
"""
from typing import Dict, List, Any, Optional
from pydantic import ValidationError
import logging

from app.domain.feature_graph_v1 import FeatureGraphV1

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of schema validation."""
    
    def __init__(
        self,
        valid: bool,
        errors: List[str] = None,
        repaired_data: Optional[Dict] = None
    ):
        self.valid = valid
        self.errors = errors or []
        self.repaired_data = repaired_data
    
    def __bool__(self) -> bool:
        return self.valid


class FeatureGraphSchemaValidator:
    """
    Validate FeatureGraph JSON against strict schema.
    
    This provides detailed validation errors for debugging and training data logging.
    """
    
    @staticmethod
    def validate_v1(data: Dict[str, Any]) -> ValidationResult:
        """
        Validate data against FeatureGraphV1 schema.
        
        Args:
            data: Parsed JSON dict from LLM
            
        Returns:
            ValidationResult with detailed errors
        """
        errors = []
        
        # Required fields check
        required_fields = ["version"]
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
        
        # Version check
        if "version" in data and data["version"] != "1.0":
            errors.append(f"Invalid version: expected '1.0', got '{data.get('version')}'")
        
        # Sketches validation
        if "sketches" in data:
            for i, sketch in enumerate(data.get("sketches", [])):
                if "id" not in sketch:
                    errors.append(f"Sketch {i}: missing 'id' field")
                if "plane" not in sketch:
                    errors.append(f"Sketch {i}: missing 'plane' field")
        
        # Features validation
        if "features" in data:
            for i, feature in enumerate(data.get("features", [])):
                if "id" not in feature:
                    errors.append(f"Feature {i}: missing 'id' field")
                if "type" not in feature:
                    errors.append(f"Feature {i}: missing 'type' field")
        
        # Try Pydantic validation for complete check
        try:
            FeatureGraphV1(**data)
        except ValidationError as e:
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                msg = error["msg"]
                errors.append(f"{loc}: {msg}")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors
        )
    
    @staticmethod
    def validate_and_repair(data: Dict[str, Any]) -> ValidationResult:
        """
        Validate and attempt to repair common issues.
        
        Returns:
            ValidationResult with repaired data if possible
        """
        errors = []
        repaired = dict(data)
        repair_applied = False
        
        # Auto-add version if missing
        if "version" not in repaired:
            repaired["version"] = "1.0"
            errors.append("Auto-repaired: added missing 'version' field")
            repair_applied = True
        
        # Auto-add empty sketches/features if missing
        if "sketches" not in repaired:
            repaired["sketches"] = []
            errors.append("Auto-repaired: added empty 'sketches' array")
            repair_applied = True
            
        if "features" not in repaired:
            repaired["features"] = []
            errors.append("Auto-repaired: added empty 'features' array")
            repair_applied = True
        
        # Auto-add parameters if missing
        if "parameters" not in repaired:
            repaired["parameters"] = {}
            errors.append("Auto-repaired: added empty 'parameters' object")
            repair_applied = True
        
        # Auto-add metadata if missing
        if "metadata" not in repaired:
            repaired["metadata"] = {}
            errors.append("Auto-repaired: added empty 'metadata' object")
            repair_applied = True
        
        # Validate the repaired data
        try:
            FeatureGraphV1(**repaired)
            return ValidationResult(
                valid=True,
                errors=errors if repair_applied else [],
                repaired_data=repaired if repair_applied else None
            )
        except ValidationError as e:
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                msg = error["msg"]
                errors.append(f"Validation failed after repair - {loc}: {msg}")
            
            return ValidationResult(
                valid=False,
                errors=errors,
                repaired_data=repaired
            )


def validate_llm_output(
    raw_response: str,
    parsed_data: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate LLM output and return detailed tracking info.
    
    Args:
        raw_response: Raw string response from LLM
        parsed_data: Parsed JSON if successful, None if parse failed
        
    Returns:
        Dict with validation info for training sample:
        - json_parse_success: bool
        - json_repair_applied: bool
        - json_validation_errors: List[str]
    """
    result = {
        "json_parse_success": parsed_data is not None,
        "json_repair_applied": False,
        "json_validation_errors": []
    }
    
    if parsed_data is None:
        result["json_validation_errors"].append("JSON parse failed")
        return result
    
    # Validate against schema
    validation = FeatureGraphSchemaValidator.validate_and_repair(parsed_data)
    
    if validation.repaired_data:
        result["json_repair_applied"] = True
        
    result["json_validation_errors"] = validation.errors
    
    return result
