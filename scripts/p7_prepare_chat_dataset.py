import json
import re
import random
from pathlib import Path

# --- Configuration ---
# Adjusted path so it runs smoothly from the project root instead of requiring cd scripts/
INPUT_DIR = Path("data/build123d_ftc/final")
OUTPUT_DIR = Path("data/final_training_dataset")
REFUSAL_FILE = OUTPUT_DIR / "refusal_samples.jsonl"

# --- Synthetic Refusal Data ---
NON_CAD_PROMPTS = [
    "Write a poem about the ocean.",
    "Can you give me a recipe for chocolate chip cookies?",
    "Write a Python script to scrape a website.",
    "Design a biological human heart.",
    "Explain the theory of general relativity.",
    "How do I fix my car's transmission?",
    "Translate this paragraph into French.",
    "Create a React component for a login button.",
    "Who won the world cup in 2022?",
    "Write a short story about a brave knight."
]

REFUSAL_RESPONSE = (
    "I am OrionFlow, a mechanical CAD copilot. I can only help generate or modify "
    "parametric CAD models using Build123d. Please provide a mechanical design request."
)

def generate_refusals(num_samples=500):
    """Generates synthetic refusal samples in ChatML format."""
    refusals = []
    for _ in range(num_samples):
        prompt = random.choice(NON_CAD_PROMPTS)
        if random.random() > 0.5:
            prompt = f"Hey, {prompt.lower()}"
            
        record = {
            "messages": [
                {"role": "system", "content": "You are OrionFlow, an AI mechanical design copilot. The user will show you existing Build123d code and request a modification. Generate the complete modified code preserving the Feature Tree Convention structure. Only change what the user requested."},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": REFUSAL_RESPONSE}
            ],
            "source": "synthetic_refusal",
            "edit_type": "refusal"
        }
        refusals.append(record)
    return refusals

def format_assistant_markdown(content: str, edit_type: str) -> str:
    """Wraps code in markdown and adds conversational padding."""
    if "```python" in content or "I am OrionFlow" in content:
        return content # Skip if already formatted or if it's a refusal

    if edit_type == "param_change":
        prefix = "I have updated the parameters as requested. Here is the modified Build123d code:\n\n"
    elif edit_type == "add_feature":
        prefix = "I have added the requested feature. Here is the updated code:\n\n"
    else:
        prefix = "Here is the Build123d code for your request:\n\n"

    return f"{prefix}```python\n{content.strip()}\n```"

def semantic_rename_parameters(code: str) -> str:
    """
    Upgraded Regex Approach: Replaces DeepCAD artifacts with clean, consistent semantics.
    """
    # 1. Base Feature Renaming
    code = re.sub(r'\bw_1_1\b', 'base_width', code)
    code = re.sub(r'\bh_1_1\b', 'base_height', code)
    code = re.sub(r'\bd_1(?:_1)?\b', 'thickness', code) # Catches d_1 and d_1_1
    code = re.sub(r'\br_1_1\b', 'radius', code)
    
    # 2. Secondary Feature Renaming
    code = re.sub(r'\bw_2_1\b', 'secondary_width', code)
    code = re.sub(r'\bh_2_1\b', 'secondary_height', code)
    code = re.sub(r'\bcx_2_1\b', 'offset_x', code)
    code = re.sub(r'\bcy_2_1\b', 'offset_y', code)
    
    # 3. Catch-all for remaining DeepCAD artifacts (prevents syntax collisions)
    code = re.sub(r'\bw_(\d+)_(\d+)\b', r'width_\1_\2', code)
    code = re.sub(r'\bh_(\d+)_(\d+)\b', r'height_\1_\2', code)
    code = re.sub(r'\bcx_(\d+)_(\d+)\b', r'offset_x_\1_\2', code)
    code = re.sub(r'\bcy_(\d+)_(\d+)\b', r'offset_y_\1_\2', code)
    code = re.sub(r'\br_(\d+)_(\d+)\b', r'radius_\1_\2', code)

    return code

def is_valid_record(record: dict, edit_type: str) -> bool:
    """Strict validation rules to prevent bad training data."""
    messages = record.get("messages", [])
    if not messages:
        return False
        
    roles = [msg.get("role") for msg in messages]
    if "system" not in roles or "user" not in roles or "assistant" not in roles:
        return False
        
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", "").strip()
            
            # Rule 1: Reject empty assistant
            if not content:
                return False
                
            # Rule 2: If it's a CAD task, enforce markdown presence
            if edit_type != "refusal":
                if "```python" not in content:
                    return False
                # Rule 3: Ensure markdown block is closed
                if not content.endswith("```"):
                    return False
                    
    return True

def process_and_merge():
    """Main pipeline execution."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_records = []
    dropped_records = 0

    # 1. Process existing CAD data
    if INPUT_DIR.exists():
        print(f"Reading data from {INPUT_DIR}...")
        for file in INPUT_DIR.glob("*.jsonl"):
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        record = json.loads(line)
                        edit_type = record.get("edit_type", "generation")
                        
                        # Process Messages
                        for msg in record.get("messages", []):
                            if msg["role"] == "assistant":
                                # Apply Semantic Renaming
                                msg["content"] = semantic_rename_parameters(msg["content"])
                                # Apply Markdown Formatting
                                msg["content"] = format_assistant_markdown(msg["content"], edit_type)
                                
                        # Run strict validation
                        if is_valid_record(record, edit_type):
                            all_records.append(record)
                        else:
                            dropped_records += 1
                            
                    except json.JSONDecodeError:
                        dropped_records += 1
                        continue
    else:
        print(f"Directory {INPUT_DIR} not found. Ensure paths are correct.")
        return

    # 2. Generate and append Refusals (10% target)
    target_refusal_count = int(len(all_records) * 0.10)
    if target_refusal_count > 0:
        print(f"Generating {target_refusal_count} synthetic refusals...")
        refusals = generate_refusals(target_refusal_count)
        all_records.extend(refusals)

        # Save standalone refusals just in case
        with open(REFUSAL_FILE, 'w', encoding='utf-8') as f:
            for r in refusals:
                f.write(json.dumps(r) + '\n')

    # 3. Shuffle and split (80/10/10)
    print("Shuffling and splitting dataset...")
    random.seed(42)
    random.shuffle(all_records)
    
    total = len(all_records)
    train_split = int(total * 0.8)
    val_split = int(total * 0.9)
    
    datasets = {
        "train.jsonl": all_records[:train_split],
        "val.jsonl": all_records[train_split:val_split],
        "test.jsonl": all_records[val_split:]
    }

    # 4. Write final clean outputs
    for filename, data in datasets.items():
        filepath = OUTPUT_DIR / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            for record in data:
                f.write(json.dumps(record) + '\n')
                
        print(f"✅ Saved {len(data)} records to {filename}")
        
    print("-" * 40)
    print(f"Total valid records retained: {total}")
    print(f"Total invalid records dropped: {dropped_records}")
    print("-" * 40)

if __name__ == "__main__":
    print("🚀 Starting OrionFlow Dataset Pipeline...")
    process_and_merge()
    print("✅ Pipeline complete. Dataset is ready for Axolotl fine-tuning.")
