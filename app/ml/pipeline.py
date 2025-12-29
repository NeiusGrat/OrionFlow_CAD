"""
Parameter inference pipeline combining ML and rule-based approaches.
Makes swapping models or adding hybrid logic trivial.
"""
from typing import Dict, Tuple
from app.intent.intent_schema import Intent
from app.ml.predictor_xgb import infer_parameters_xgb
import app.ml.parameter_infer as rules


class ParameterPipeline:
    """
    Combines ML predictions with rule-based constraints.
    Enables easy model swapping and hybrid decision logic.
    """
    
    def __init__(self, ml_enabled: bool = True):
        """
        Initialize the parameter pipeline.
        
        Args:
            ml_enabled: Whether to use ML predictions (can disable for debugging)
        """
        self.ml_enabled = ml_enabled
    
    def infer(self, intent: Intent, prompt: str) -> Tuple[Dict[str, float], Dict[str, str]]:
        """
        Returns final parameters after ML + Rules fusion.
        
        Args:
            intent: Parsed intent object
            prompt: User's text prompt
            
        Returns:
            Tuple of (parameters dict, units dict)
        """
        # Rule-based extraction (handles explicit units and geometry)
        rule_params, param_units = rules.infer_parameters(intent, prompt)
        
        if not self.ml_enabled:
            return rule_params, param_units
        
        # ML-based prediction (learns from patterns)
        ml_params = infer_parameters_xgb(intent, prompt)
        
        # Decision Strategy: Use rules for explicit inputs, ML for implicit
        # Currently prioritizing rules (as per existing logic)
        # Future: Could blend based on confidence scores
        final_params = rule_params.copy()
        
        # Potential future enhancement: confidence-based blending
        # for key in rule_params.keys():
        #     if rule_params[key] == default_value and ml_confidence > threshold:
        #         final_params[key] = ml_params.get(key, rule_params[key])
        
        return final_params, param_units
    
    def get_ml_comparison(self, intent: Intent, prompt: str) -> Dict[str, Dict[str, float]]:
        """
        Get comparison between ML and rule-based predictions for debugging.
        
        Args:
            intent: Parsed intent object
            prompt: User's text prompt
            
        Returns:
            Dictionary with 'rules' and 'ml' predictions
        """
        rule_params, _ = rules.infer_parameters(intent, prompt)
        ml_params = infer_parameters_xgb(intent, prompt)
        
        return {
            "rules": rule_params,
            "ml": ml_params
        }
