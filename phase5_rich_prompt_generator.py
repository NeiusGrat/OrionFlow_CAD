import os
import json
import time
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
# Using Gemini 2.5 Flash as requested for high rate limits and speed
model = genai.GenerativeModel('gemini-2.5-flash')

INPUT_FILE = Path("data/ofl_validated_final.jsonl")
OUTPUT_FILE = Path("data/training/ofl_finetune_data_v2.jsonl")
CHECKPOINT_FILE = Path("data/training/phase5_checkpoint.json")

BATCH_SIZE = 15     # Number of scripts per LLM call (Increased for speed)
SAVE_EVERY = 5      # Batches to process before writing to disk (75 scripts)
RPM_LIMIT = 12      # Free tier limit (requests per minute)
SLEEP_TIME = 60.0 / RPM_LIMIT # Seconds to wait between requests to stay under 12 RPM

SYSTEM_PROMPT = """You are a senior mechanical design engineer with 15+ years experience creating training data for Orionflow.

Given {batch_size} complete OFL Python scripts below, for EACH script write exactly ONE realistic natural-language prompt that a real engineer would type to request that part.

Rules:
- Sound 100% natural (real engineer language)
- Include all visible dimensions and obvious standards (6205, M8, H7, ISO, etc.)
- Mention manufacturing if obvious (CNC millable, 3D printable, etc.)
- Never mention code, OFL, Python, or "generate code"
- The prompt should just be the physical description of the part (e.g. "Bearing housing block for a 6205 bearing..."). DO NOT append phrases like "Generate the OFL code for this part."
- Vary the styles across the scripts naturally (some concise, some detailed).
- Return ONLY a valid JSON array of {expected_prompts} strings (1 prompt per script) in the exact same order as the scripts provided. No extra text, no markdown blocks. Just the raw JSON array.

Here are the {batch_size} OFL scripts:
{scripts}
"""

UNSLOTH_SYSTEM_PROMPT = "You are Orionflow, an expert AI CAD copilot. The user will describe a mechanical part. Your job is to output the pure OFL Python code for that part."

def extract_json(text):
    """Safely extract JSON array from Gemini's response, handling potential markdown."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())

def process_batch(scripts):
    """Send a batch of scripts to Gemini and return the generated prompts."""
    # Format scripts for the prompt
    scripts_text = ""
    for i, script in enumerate(scripts):
        scripts_text += f"\n--- SCRIPT {i+1} ---\n{script['code']}\n"
    
    prompt = SYSTEM_PROMPT.format(
        batch_size=len(scripts), 
        expected_prompts=len(scripts),
        scripts=scripts_text
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # We use a slight temperature to get good variation in engineering terminology
            response = model.generate_content(prompt, generation_config={"temperature": 0.4})
            
            prompts = extract_json(response.text)
            
            if len(prompts) != len(scripts):
                raise ValueError(f"Expected {len(scripts)} prompts, but received {len(prompts)}.")
                
            return prompts
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"\n[Warning] API call failed ({str(e)}). Retrying in {SLEEP_TIME * 2}s...")
                time.sleep(SLEEP_TIME * 2)
            else:
                print(f"\n[Error] Batch failed after {max_retries} attempts: {str(e)}")
                return None
            
def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)["processed_count"]
    return 0

def save_checkpoint(count):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"processed_count": count}, f)

def main():
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Load all validated pairs
    all_pairs = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_pairs.append(json.loads(line))
                
    total_scripts = len(all_pairs)
    processed_count = load_checkpoint()
    
    print(f"Total scripts to process: {total_scripts}")
    print(f"Resuming from script index: {processed_count}")
    
    # Open file in append mode
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out:
        
        # Batching logic
        batches_processed_since_save = 0
        
        with tqdm(total=total_scripts, initial=processed_count, desc="Generating Prompts") as pbar:
            for i in range(processed_count, total_scripts, BATCH_SIZE):
                batch = all_pairs[i:i + BATCH_SIZE]
                
                # Rate limit pacing
                time.sleep(SLEEP_TIME)
                
                generated_prompts = process_batch(batch)
                
                if generated_prompts:
                    # Match the single prompt back to each script
                    for script_idx, script in enumerate(batch):
                        prompt_text = generated_prompts[script_idx]
                        
                        sharegpt_record = {
                            "messages": [
                                {"role": "system", "content": UNSLOTH_SYSTEM_PROMPT},
                                {"role": "user", "content": prompt_text},
                                {"role": "assistant", "content": script["code"]}
                            ]
                        }
                        
                        f_out.write(json.dumps(sharegpt_record, ensure_ascii=False) + "\n")
                        
                    pbar.update(len(batch))
                    processed_count += len(batch)
                    batches_processed_since_save += 1
                    
                    # Checkpoint
                    if batches_processed_since_save >= SAVE_EVERY:
                        f_out.flush() # Ensure it's on disk
                        save_checkpoint(processed_count)
                        batches_processed_since_save = 0
                else:
                    print(f"\n[FATAL] Stopping process at index {processed_count} due to repeated API failures.")
                    break
                    
    # Final checkpoint save
    save_checkpoint(processed_count)
    print(f"\nFinished processing. Total prompt pairs generated so far: {processed_count * 2}")

if __name__ == "__main__":
    main()
