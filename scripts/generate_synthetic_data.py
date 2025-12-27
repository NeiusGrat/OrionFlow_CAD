
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict

# Ensure we can import from app
sys.path.append(os.getcwd())

from app.agent.llm_client import LLMClient
from app.cad.generation_engine import execute_build123d_script, Build123dExecutionError
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
OUTPUT_DIR = Path("data/training")
OUTPUT_FILE = OUTPUT_DIR / "synthetic_dataset.jsonl"
CONCURRENCY_LIMIT = 3 # Avoid hitting Groq rate limits too hard

SEED_PROMPTS = [
    "A 10x10x10 cube",
    "A cylinder with radius 5 and height 20",
    "A sphere with radius 15",
    "A rectangular plate 50x20 with thickness 5",
    "A pipe with outer radius 10, inner radius 8, length 30",
    "A 20x20x20 cube with a 5mm hole in the top center",
    "A washer with outer radius 10, inner hole 5, thickness 2",
    "A cone with bottom radius 10, top radius 0, height 20",
    "A torus with major radius 20 and minor radius 5",
    "A simple L-bracket with arms 50mm long, 20mm wide, 5mm thick",
    "A box with fillets on all edges, radius 2",
    "A cylinder with a chamfer on the top edge",
    "A hex nut shape (no threads) for M6 bolt",
    "A simple baseplate with 4 mounting holes in corners",
    "A 100x10x10 beam",
    "A hollow box 20x20x20 with 2mm wall thickness",
    "A T-junction of two usage pipes",
    "A simple staircase with 3 steps",
    "A star shape extruded to 5mm thickness",
    "A gear blank (cylinder) with a center D-shaft hole"
]

async def process_prompt(sem: asyncio.Semaphore, llm: LLMClient, prompt: str) -> Dict:
    """
    Generates code for a prompt, validates it, and returns the data entry if successful.
    """
    async with sem:
        print(f"Generating for: '{prompt}'...")
        try:
            # 1. Generate
            code = await llm.generate_cad_script(prompt)
            
            # 2. Validate
            execute_build123d_script(code)
            
            # 3. Success
            print(f"✅ Success: '{prompt}'")
            return {
                "instruction": prompt,
                "input": "",
                "output": code
            }
            
        except Build123dExecutionError as e:
            print(f"❌ Validation Failed for '{prompt}': {e}")
            return None
        except Exception as e:
            print(f"❌ Error for '{prompt}': {e}")
            return None

async def main():
    # Setup
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    llm = LLMClient()
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    tasks = []
    
    print(f"Starting generation for {len(SEED_PROMPTS)} prompts...")
    start_time = time.time()
    
    # Create Tasks
    for prompt in SEED_PROMPTS:
        tasks.append(process_prompt(sem, llm, prompt))
    
    # Run
    results = await asyncio.gather(*tasks)
    
    # Filter and Save
    valid_entries = [r for r in results if r is not None]
    
    print(f"\n--- Summary ---")
    print(f"Total: {len(SEED_PROMPTS)}")
    print(f"Valid: {len(valid_entries)}")
    print(f"Time: {time.time() - start_time:.2f}s")
    
    with open(OUTPUT_FILE, "a") as f: # Append mode
        for entry in valid_entries:
            f.write(json.dumps(entry) + "\n")
            
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
