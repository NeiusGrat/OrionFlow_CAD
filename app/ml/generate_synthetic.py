import pandas as pd
import random
import os
from pathlib import Path
from app.ml.feature_encoder import encode, flatten_features

TRAIN_DIR = Path("data/training")
TRAIN_DIR.mkdir(parents=True, exist_ok=True)

def generate_box_data(cols, n_samples=1000):
    data = []
    
    for _ in range(n_samples):
        # 1. Decide Ground Truth Dimensions (Engineering Logic)
        category = random.choice(["tiny", "small", "medium", "large", "thin", "plate"])
        
        if category == "tiny":
            l, w, h = random.uniform(2, 5), random.uniform(2, 5), random.uniform(2, 5)
            prompt_base = random.choice(["tiny box", "small cube", "little block"])
        elif category == "small":
            l, w, h = random.uniform(10, 30), random.uniform(10, 30), random.uniform(10, 30)
            prompt_base = random.choice(["box", "cube", "block"])
        elif category == "medium":
            l, w, h = random.uniform(40, 80), random.uniform(40, 80), random.uniform(40, 80)
            prompt_base = random.choice(["medium box", "storage box", "container"])
        elif category == "large":
            l, w, h = random.uniform(100, 200), random.uniform(100, 200), random.uniform(100, 200)
            prompt_base = random.choice(["large box", "giant cube", "huge block"])
        elif category == "thin":
            l, w = random.uniform(20, 100), random.uniform(20, 100)
            h = random.uniform(1, 5) 
            prompt_base = random.choice(["thin plate", "sheet", "panel"])
        else: # plate
             l, w = random.uniform(50, 150), random.uniform(50, 100)
             h = random.uniform(5, 15)
             prompt_base = random.choice(["plate", "base"])

        # 2. Add variation to prompt
        prompt = prompt_base
        if random.random() < 0.3:
            prompt += " " + random.choice(["for testing", "demo", "sample", "please"])
            
        # 3. Simulate explicit dimensions sometimes
        # Note: In a real regressor, we might want separate models for explicit vs implicit.
        # But for this demo, we teach it that "tiny" -> small dims, etc.
        # If specific numbers are in prompt, the rule layer handles them. 
        # ML is mostly for the 'vague' cases. 
        
        # Encode
        features = encode(prompt)
        
        # Create row
        row = flatten_features(features)
        # Append targets
        row.extend([l, w, h])
        
        data.append(row)

    # Get feature keys for header
    feature_keys = sorted(encode("dummy").keys())
    all_cols = feature_keys + ["length", "width", "height"]
    
    df = pd.DataFrame(data, columns=all_cols)
    return df

def generate_cylinder_data(n_samples=1000):
   # Similar logic pattern for cylinder...
   data = []
   for _ in range(n_samples):
       category = random.choice(["rod", "disc", "pipe", "pole"])
       
       if category == "rod": # long thin
           r = random.uniform(2, 5)
           h = random.uniform(50, 200)
           prompt_base = "rod"
       elif category == "disc": # wide short
           r = random.uniform(20, 50)
           h = random.uniform(2, 10)
           prompt_base = "disc"
       elif category == "pipe":
           r = random.uniform(10, 30)
           h = random.uniform(50, 100)
           prompt_base = "pipe"
       else: 
           r = random.uniform(5, 15)
           h = random.uniform(20, 60)
           prompt_base = "cylinder"
           
       if random.random() < 0.5: prompt_base = "small " + prompt_base
       
       features = encode(prompt_base)
       row = flatten_features(features)
       row.extend([r, h])
       data.append(row)
       
   feature_keys = sorted(encode("dummy").keys())
   all_cols = feature_keys + ["radius", "height"]
   return pd.DataFrame(data, columns=all_cols)


if __name__ == "__main__":
    print("Generating synthetic data...")
    
    df_box = generate_box_data(None)
    df_box.to_csv(TRAIN_DIR / "box_params.csv", index=False)
    print(f"Saved box_params.csv ({len(df_box)} rows)")

    df_cyl = generate_cylinder_data()
    df_cyl.to_csv(TRAIN_DIR / "cylinder_params.csv", index=False)
    print(f"Saved cylinder_params.csv ({len(df_cyl)} rows)")
