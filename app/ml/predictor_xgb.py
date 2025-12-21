import xgboost as xgb
import pandas as pd
from pathlib import Path
from app.intent.intent_schema import Intent
from app.ml.feature_encoder import encode, flatten_features
from app.intent.symbols import extract_numbers

MODEL_DIR = Path("app/ml/models")

class XGBPredictor:
    def __init__(self):
        self.models = {}
        self.loaded = False

    def load_models(self):
        if self.loaded: return
        
        # Helper to load safely
        def load(name):
            p = MODEL_DIR / f"{name}.json"
            if p.exists():
                model = xgb.XGBRegressor()
                model.load_model(p)
                self.models[name] = model
        
        load("box_length")
        load("box_width")
        load("box_height")
        load("cylinder_radius")
        load("cylinder_height")
        self.loaded = True

    def predict(self, intent: Intent, prompt: str) -> dict:
        self.load_models()
        
        # 1. Encode prompt
        features = encode(prompt)
        X_list = flatten_features(features)
        
        # DataFrame wrapper for XGBoost (needs feature names typically, or just ignore if order matches)
        # To be safe and fast, we just pass array, assuming strict order matching with training.
        # Ideally we'd use DMatrix or DataFrame with cols.
        # Let's use simple list wrap since we control encoder.
        # Note: XGBoost sklearn wrapper expects 2D array.
        X_reshaped = [X_list] 
        
        params = {}
        
        if intent.part_type == "box":
            # Predictions
            # Default fallback if model missing
            l = self.models["box_length"].predict(X_reshaped)[0] if "box_length" in self.models else 10.0
            w = self.models["box_width"].predict(X_reshaped)[0] if "box_width" in self.models else 10.0
            h = self.models["box_height"].predict(X_reshaped)[0] if "box_height" in self.models else 10.0
            
            params = {"length": float(l), "width": float(w), "height": float(h)}
            
            # RULE BLENDING (Critical Step)
            # If user explicitly said numbers, override ML
            nums = extract_numbers(prompt)
            if len(nums) == 3: # "10x20x30" or "10 20 30"
                 params["length"], params["width"], params["height"] = nums
            elif len(nums) == 2: # "10x20 box" -> usually L x W, H default
                 params["length"], params["width"] = nums
                 # keep ML guessed height or a safe default
            elif len(nums) == 1: # "size 10" -> cube?
                 params["length"] = params["width"] = params["height"] = nums[0]

        elif intent.part_type == "cylinder":
             r = self.models["cylinder_radius"].predict(X_reshaped)[0] if "cylinder_radius" in self.models else 5.0
             h = self.models["cylinder_height"].predict(X_reshaped)[0] if "cylinder_height" in self.models else 10.0
             
             params = {"radius": float(r), "height": float(h)}
             
             nums = extract_numbers(prompt)
             if len(nums) == 2:
                 params["radius"], params["height"] = nums[0], nums[1] # risky assumption radius first, but better than nothing
             elif len(nums) == 1:
                 # "radius 5" or "height 10"? 
                 # Here we could check keywords near number.
                 # For now, simplistic blend: if "radius" word exists, assume radius.
                 if "radius" in prompt or "rad" in prompt or "r" in prompt:
                     params["radius"] = nums[0]
                 elif "height" in prompt or "long" in prompt:
                     params["height"] = nums[0]
        
        elif intent.part_type == "shaft":
            # Just reuse cylinder logic or have separate models
            # For this demo, map to cylinder models but maybe different manual overrides
             r = self.models["cylinder_radius"].predict(X_reshaped)[0] if "cylinder_radius" in self.models else 2.5
             h = self.models["cylinder_height"].predict(X_reshaped)[0] if "cylinder_height" in self.models else 50.0
             params = {"radius": float(r), "height": float(h)}
             
        return params

# Singleton instance
predictor = XGBPredictor()

def infer_parameters_xgb(intent: Intent, prompt: str) -> dict:
    return predictor.predict(intent, prompt)
