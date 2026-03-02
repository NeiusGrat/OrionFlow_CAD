import os
import json
import time
import random
import google.generativeai as genai
from pathlib import Path
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

# Verify API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

INPUT_FILE = Path("data/training/ofl_finetune_data.jsonl")      # 42k baseline
OUTPUT_FILE = Path("data/training/ofl_finetune_data_hybrid.jsonl") # 54k hybrid
CHECKPOINT_FILE = Path("data/training/phase5_paraphrase_checkpoint.json")

TARGET_LLM_SAMPLES = 12000
BATCH_SIZE = 15     # Number of prompts per LLM call
SAVE_EVERY = 5      # Batches to process before writing to disk
RPM_LIMIT = 13      # Free tier limit (safe margin)
SLEEP_TIME = 60.0 / RPM_LIMIT 

SYSTEM_PROMPT = """You are a senior mechanical design engineer with 15+ years experience.
I will give you {batch_size} basic, boring CAD descriptions. Your job is to PARAPHRASE each of them into exactly ONE realistic natural-language prompt that a real engineer would type into an AI CAD system.

Rules for rewriting:
- Sound 100% natural and professional (real engineer language).
- If the description mentions primitive shapes (e.g. "rectangular profile extruded into 3D"), rewrite it as a real mechanical part (e.g. "CNC milled aluminum base plate", "bearing block").
- Maintain all implied physical geometries (holes, fillets, chamfers).
- Include standard engineering terminology (e.g. M8 holes, ISO standards, H7 fit, wall thickness) to add realistic flavor.
- NEVER mention code, OFL, Python, or "generate code" or "write code". The prompt must just be the physical description of the part.
- Vary the styles naturally across the {batch_size} prompts (some very concise, some highly detailed functional descriptions).
- Return ONLY a valid JSON array of {batch_size} strings in the EXACT SAME ORDER as provided. No extra text, no markdown blocks. Just the raw JSON array.

Original Prompts:
{prompts}
"""

def extract_json(text):
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    if text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return json.loads(text.strip())

def process_batch(prompts):
    prompts_text = ""
    for i, p in enumerate(prompts):
        prompts_text += f"\n--- PROMPT {i+1} ---\n{p}\n"
    
    prompt = SYSTEM_PROMPT.format(batch_size=len(prompts), prompts=prompts_text)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, generation_config={"temperature": 0.5})
            results = extract_json(response.text)
            
            if len(results) != len(prompts):
                raise ValueError(f"Expected {len(prompts)} prompts, but received {len(results)}.")
                
            return results
            
        except Exception as e:
            if attempt < max_retries - 1:
                # If it's a quota error or simple timeout, we need a long backoff
                wait_time = 65.0 
                print(f"\n[Warning] API call failed ({str(e)}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"\n[Error] Batch failed after {max_retries} attempts: {str(e)}")
                return None

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
            return data["processed_count"], set(data["sampled_indices"])
    return 0, set()

def save_checkpoint(count, sampled_indices):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"processed_count": count, "sampled_indices": list(sampled_indices)}, f)

def perform_stratified_sampling(all_pairs, target_size):
    """Samples exactly target_size pairs while maintaining geometric diversity."""
    print("Performing stratified sampling based on geometric features...")
    
    strata = {}
    for i, pair in enumerate(all_pairs):
        meta = pair.get("metadata", {})
        
        # Create a unique key for the strata based on the features
        # E.g. "rect_True-circ_False-hole_True-add_False-plane_XY"
        key = f"rect_{meta.get('has_rect', False)}-circ_{meta.get('has_circ', False)}-hole_{meta.get('has_hole', False)}-add_{meta.get('has_additive', False)}-plane_{meta.get('plane', 'XY')}"
        
        if key not in strata:
            strata[key] = []
        strata[key].append(i)
        
    print(f"Found {len(strata)} unique geometric strata.")
    
    sampled_indices = []
    
    # Calculate how many to take from each stratum proportionally
    total_population = len(all_pairs)
    for key, indices in strata.items():
        proportion = len(indices) / total_population
        take_count = int(proportion * target_size)
        
        # Ensure we take at least 1 if the stratum exists, unless target size is reached
        take_count = max(1, take_count)
        
        if len(indices) <= take_count:
            sampled_indices.extend(indices)
        else:
            sampled_indices.extend(random.sample(indices, take_count))
            
    # Adjust to exact target size
    if len(sampled_indices) > target_size:
        sampled_indices = random.sample(sampled_indices, target_size)
    elif len(sampled_indices) < target_size:
        # Fill the remainder randomly from unsampled items
        unsampled = list(set(range(total_population)) - set(sampled_indices))
        sampled_indices.extend(random.sample(unsampled, target_size - len(sampled_indices)))
        
    random.shuffle(sampled_indices)
    print(f"Sampling complete. Selected {len(sampled_indices)} robust examples.")
    return sampled_indices

def main():
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found. Run phase4 first.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Load all baseline pairs
    all_pairs = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_pairs.append(json.loads(line))
                
    total_baseline = len(all_pairs)
    print(f"Loaded {total_baseline} baseline pairs.")
    
    processed_count, previously_sampled_indices = load_checkpoint()
    
    # Stratified Sampling Strategy
    if previously_sampled_indices:
        print(f"Resuming with {len(previously_sampled_indices)} previously sampled indices.")
        sampled_indices = list(previously_sampled_indices)
    else:
        # Initialize Output File with all 42k deterministic pairs first!
        # Because we want a 54k hybrid file (42k original + 12k paraphrased)
        print("Writing the 42,200 baseline pairs to the hybrid output file...")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
            for pair in all_pairs:
                # Remove metadata to keep dataset clean
                clean_pair = {"messages": pair["messages"]}
                f_out.write(json.dumps(clean_pair, ensure_ascii=False) + "\n")
        
        val_target = min(TARGET_LLM_SAMPLES, total_baseline)
        sampled_indices = perform_stratified_sampling(all_pairs, val_target)
        save_checkpoint(0, sampled_indices)
    
    # We only process the LLM generated ones now
    remaining_indices = sampled_indices[processed_count:]
    print(f"Generating paraphrased prompts for {len(remaining_indices)} remaining sampled models...")
    
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out:
        
        batches_processed_since_save = 0
        
        with tqdm(total=TARGET_LLM_SAMPLES, initial=processed_count, desc="LLM Paraphrasing") as pbar:
            for ptr in range(0, len(remaining_indices), BATCH_SIZE):
                batch_indices = remaining_indices[ptr:ptr + BATCH_SIZE]
                
                # Extract just the user prompts
                batch_prompts = []
                for idx in batch_indices:
                    msgs = all_pairs[idx]["messages"]
                    user_msg = next(m["content"] for m in msgs if m["role"] == "user")
                    batch_prompts.append(user_msg)
                
                time.sleep(SLEEP_TIME)
                
                paraphrased_prompts = process_batch(batch_prompts)
                
                if paraphrased_prompts:
                    for i, idx in enumerate(batch_indices):
                        # Construct a NEW pair with the paraphrased prompt, but original code
                        original_pair = all_pairs[idx]
                        code = next(m["content"] for m in original_pair["messages"] if m["role"] == "assistant")
                        sys_prompt = next(m["content"] for m in original_pair["messages"] if m["role"] == "system")
                        
                        sharegpt_record = {
                            "messages": [
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": paraphrased_prompts[i]},
                                {"role": "assistant", "content": code}
                            ]
                        }
                        f_out.write(json.dumps(sharegpt_record, ensure_ascii=False) + "\n")
                        
                    processed_count += len(batch_indices)
                    batches_processed_since_save += 1
                    pbar.update(len(batch_indices))
                    
                    if batches_processed_since_save >= SAVE_EVERY:
                        f_out.flush()
                        save_checkpoint(processed_count, sampled_indices)
                else:
                    print(f"\n[FATAL] API failed repeatedly. Stopping at {processed_count}.")
                    break
                    
    save_checkpoint(processed_count, sampled_indices)
    print(f"\nFinished hybrid generation! Total file lines: {len(all_pairs) + processed_count}")

if __name__ == "__main__":
    main()
