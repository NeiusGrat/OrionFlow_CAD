import json
import random
from pathlib import Path

INPUT_FILE = Path("data/training/ofl_finetune_data_v2.jsonl")
NUM_SAMPLES = 20

def validate_prompts():
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found. Run phase5 first.")
        return

    pairs = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    pairs.append(json.loads(line))
                except:
                    pass
                    
    if not pairs:
        print("Dataset is empty.")
        return
        
    print(f"Loaded {len(pairs)} prompt-completion pairs.")
    print(f"Sampling {NUM_SAMPLES} random entries for validation...\n")
    print("="*80)
    
    samples = random.sample(pairs, min(NUM_SAMPLES, len(pairs)))
    
    for i, sample in enumerate(samples):
        print(f"\n--- SAMPLE {i+1} ---")
        messages = sample.get('messages', [])
        sys_prompt = next((m['content'] for m in messages if m['role'] == 'system'), 'MISSING_SYS')
        user_prompt = next((m['content'] for m in messages if m['role'] == 'user'), 'MISSING_USER')
        code = next((m['content'] for m in messages if m['role'] == 'assistant'), 'MISSING_CODE')
        
        print(f"SYSTEM:\n{sys_prompt}")
        print(f"USER:\n{user_prompt}")
        print("-" * 40)
        # Just print the first few lines of code to save terminal space
        code_preview = "\n".join(code.split("\n")[:8])
        print(f"ASSISTANT (Preview):\n{code_preview}...")
        print("="*80)

if __name__ == "__main__":
    validate_prompts()
