import pandas as pd
import xgboost as xgb
import os
import pickle
from pathlib import Path

DATA_DIR = Path("data/training")
MODEL_DIR = Path("app/ml/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def train_box_models():
    print("Training Box Models...")
    df = pd.read_csv(DATA_DIR / "box_params.csv")
    
    # Drop targets to get X
    X = df.drop(columns=["length", "width", "height"])
    
    # Train separate regressors
    targets = ["length", "width", "height"]
    for t in targets:
        print(f"  Training {t} regressor...")
        model = xgb.XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1)
        model.fit(X, df[t])
        
        # Save
        model.get_booster().save_model(MODEL_DIR / f"box_{t}.json")
    print("Box models saved.")

def train_cylinder_models():
    print("Training Cylinder Models...")
    df = pd.read_csv(DATA_DIR / "cylinder_params.csv")
    
    X = df.drop(columns=["radius", "height"])
    
    targets = ["radius", "height"]
    for t in targets:
        print(f"  Training {t} regressor...")
        model = xgb.XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1)
        model.fit(X, df[t])
        
        model.get_booster().save_model(MODEL_DIR / f"cylinder_{t}.json")
    print("Cylinder models saved.")


if __name__ == "__main__":
    if not (DATA_DIR / "box_params.csv").exists():
        print("Data not found! Run generate_synthetic.py first.")
        exit(1)
        
    train_box_models()
    train_cylinder_models()
