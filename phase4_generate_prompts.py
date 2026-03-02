import json
import random
from pathlib import Path
from tqdm import tqdm

INPUT_FILE = Path("data/ofl_validated_final.jsonl")
OUTPUT_FILE = Path("data/training/ofl_finetune_data.jsonl")

# Prompt templates to add natural language variance so the LLM doesn't overfit
# on a single sentence structure.
GENERIC_INTRO = [
    "Write OrionFlow (OFL) code to build the following CAD model.",
    "Generate the OFL script for this mechanical part.",
    "Draft the CAD code in OrionFlow to create the following object:",
    "Provide the OFL script for a 3D model with these characteristics:",
    "Create an OrionFlow script that designs the following component:"
]

UNSLOTH_SYSTEM_PROMPT = "You are Orionflow, an expert AI CAD copilot. The user will describe a mechanical part. Your job is to output the pure OFL Python code for that part."

def analyze_ofl(code: str) -> str:
    """
    Very fast substring-based AST analyzer.
    Reads the raw OFL code and produces a semantic text description of what it does.
    """
    description = []
    
    # Base sketch shapes
    has_rect = ".rect(" in code
    has_circ = ".circle(" in code
    has_poly = ".polygon(" in code or ".polyline(" in code
    
    if has_rect and not has_circ:
        description.append("It is based on a rectangular profile")
    elif has_circ and not has_rect:
        description.append("It is based on a circular/cylindrical profile")
    elif has_rect and has_circ:
        description.append("The design incorporates both rectangular and circular base profiles")
    elif has_poly:
        description.append("It uses a custom polygonal or irregular sketch profile")
    else:
        description.append("A solid 3D part")

    # 3D Operations
    if ".extrude(" in code:
        description[-1] += " that is extruded into 3D."
    elif ".revolve(" in code:
        description[-1] += " that is revolved into 3D."
    elif ".sweep(" in code:
        description[-1] += " that is swept along a path."
    elif ".loft(" in code:
        description[-1] += " created via a loft operation."
    else:
        description[-1] += "."

    # Secondary Features
    features = []
    
    if ".hole(" in code or "hole" in code.lower():
        features.append("internal holes/cutouts")
    if ".circle(" in code and has_rect:  # Circles cutting into rectangles are usually holes
        features.append("circular cutouts")
    
    if ".fillet(" in code:
        features.append("rounded fillet edges")
    if ".chamfer(" in code:
        features.append("chamfered edges")
        
    if "Plane.XZ" in code or "Plane.YZ" in code or "Workplane" in code:
        features.append("sketching on multiple intersecting planes")
        
    if "mirror(" in code:
        features.append("mirrored geometry")
        
    if "pattern(" in code or "polar_array" in code or "grid_array" in code:
        features.append("a repeating array pattern")

    if features:
        # Join features naturally: "a, b, and c"
        if len(features) == 1:
            feat_str = features[0]
        elif len(features) == 2:
            feat_str = f"{features[0]} and {features[1]}"
        else:
            feat_str = ", ".join(features[:-1]) + f", and {features[-1]}"
            
        description.append(f"The part features {feat_str}.")

    # Parameterization check
    lines = code.split("\n")
    param_count = sum(1 for line in lines if "=" in line and ("Sketch" not in line and "export" not in line))
    if param_count > 3:
        description.append(f"The code should declare several ({param_count}+) core dimensional variables at the top for clean parameterization.")

    return " ".join(description)


def generate_prompts():
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found. Run validation first.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    total_lines = sum(1 for _ in open(INPUT_FILE, "r", encoding="utf-8"))
    print(f"Generating Semantic Prompts for {total_lines} models...")
    
    count = 0
    with open(INPUT_FILE, "r", encoding="utf-8") as f_in, \
         open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
         
        for line in tqdm(f_in, total=total_lines):
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
                code_str = data["code"]
                
                # Generate dynamic description based on the specific code
                semantic_desc = analyze_ofl(code_str)
                intro = random.choice(GENERIC_INTRO)
                
                full_prompt = f"{intro}\n\nRequirements:\n- {semantic_desc}\n- Use pure OFL syntax with no markdown wrappers."
                
                sharegpt_record = {
                    "messages": [
                        {"role": "system", "content": UNSLOTH_SYSTEM_PROMPT},
                        {"role": "user", "content": full_prompt},
                        {"role": "assistant", "content": code_str}
                    ],
                    "metadata": {
                        "has_rect": ".rect(" in code_str,
                        "has_circ": ".circle(" in code_str,
                        "has_poly": ".polygon(" in code_str or ".polyline(" in code_str,
                        "has_hole": ".hole(" in code_str or ("hole" in code_str.lower()),
                        "has_additive": ".fillet(" in code_str or ".chamfer(" in code_str,
                        "plane": "XY" if "Plane.XY" in code_str else ("XZ" if "Plane.XZ" in code_str else ("YZ" if "Plane.YZ" in code_str else "Mixed"))
                    }
                }
                
                f_out.write(json.dumps(sharegpt_record, ensure_ascii=False) + "\n")
                count += 1
                
            except Exception as e:
                # Catch JSON errors or parsing bugs
                pass
                
    print(f"\nDone! Successfully generated {count} semantic prompt-completion pairs.")
    print(f"File saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_prompts()
