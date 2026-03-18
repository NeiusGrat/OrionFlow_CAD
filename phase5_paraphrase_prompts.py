import os
import json
import time
import asyncio
import aiohttp
import random
from pathlib import Path
from dotenv import dotenv_values
from tqdm.asyncio import tqdm

# ---- CONFIG ----
ENV_VARS = dotenv_values(".env")
API_KEYS = [v for k, v in ENV_VARS.items() if 'GEMINI' in k and v]

if not API_KEYS:
    raise ValueError("No GEMINI API keys found in .env file!")

BATCH_SIZE = 10
INPUT_FILE = Path("data/training/ofl_finetune_data.jsonl")      # 42k baseline
OUTPUT_FILE = Path("data/training/ofl_finetune_data_hybrid.jsonl") # 54k hybrid
CHECKPOINT_FILE = Path("data/training/phase5_paraphrase_checkpoint.json")
TARGET_LLM_SAMPLES = 12000

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

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
            return data["processed_count"], set(data["sampled_indices"])
    return 0, set()

def save_checkpoint(count, sampled_indices):
    tmp = str(CHECKPOINT_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"processed_count": count, "sampled_indices": list(sampled_indices)}, f)
    os.replace(tmp, CHECKPOINT_FILE)

def perform_stratified_sampling(all_pairs, target_size):
    print("Performing stratified sampling based on geometric features...")
    strata = {}
    for i, pair in enumerate(all_pairs):
        meta = pair.get("metadata", {})
        key = f"rect_{meta.get('has_rect', False)}-circ_{meta.get('has_circ', False)}-hole_{meta.get('has_hole', False)}-add_{meta.get('has_additive', False)}-plane_{meta.get('plane', 'XY')}"
        if key not in strata: strata[key] = []
        strata[key].append(i)
        
    sampled_indices = []
    total_population = len(all_pairs)
    for key, indices in strata.items():
        proportion = len(indices) / total_population
        take_count = max(1, int(proportion * target_size))
        if len(indices) <= take_count:
            sampled_indices.extend(indices)
        else:
            sampled_indices.extend(random.sample(indices, take_count))
            
    if len(sampled_indices) > target_size:
        sampled_indices = random.sample(sampled_indices, target_size)
    elif len(sampled_indices) < target_size:
        unsampled = list(set(range(total_population)) - set(sampled_indices))
        sampled_indices.extend(random.sample(unsampled, target_size - len(sampled_indices)))
        
    random.shuffle(sampled_indices)
    return sampled_indices

# --- ASYNC WORKER ---
WRITE_LOCK = asyncio.Lock()
PROCESSED_COUNT = 0

async def worker(worker_id, api_key, queue, pbar, all_pairs, sampled_indices):
    global PROCESSED_COUNT
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # Stagger workers so they don't blast the server at the exact same millisecond
    await asyncio.sleep(worker_id * 7.5)
    
    async with aiohttp.ClientSession() as session:
        while True:
            batch_indices = await queue.get()
            if batch_indices is None:
                break
                
            prompts_text = ""
            for i, idx in enumerate(batch_indices):
                msgs = all_pairs[idx]["messages"]
                user_msg = next(m["content"] for m in msgs if m["role"] == "user")
                prompts_text += f"\n--- PROMPT {i+1} ---\n{user_msg}\n"
                
            prompt = SYSTEM_PROMPT.format(batch_size=len(batch_indices), prompts=prompts_text)
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.5}
            }
            
            retry = 0
            while True:
                try:
                    async with session.post(url, json=payload, headers={'Content-Type': 'application/json'}) as resp:
                        if resp.status == 429:
                            retry += 1
                            sleep_time = min(2.0 ** retry, 60.0) + random.uniform(0, 2)
                            print(f"\\n[Worker {worker_id}] 429 Quota Exceeded. Sleeping {sleep_time:.2f}s (Retry {retry})")
                            await asyncio.sleep(sleep_time)
                            continue
                        
                        if resp.status != 200:
                            err_txt = await resp.text()
                            if "quota" in err_txt.lower() or "exhausted" in err_txt.lower():
                                retry += 1
                                sleep_time = min(2.0 ** retry, 60.0) + random.uniform(0, 2)
                                await asyncio.sleep(sleep_time)
                                continue
                            print(f"\n[Worker {worker_id}] API Error {resp.status}: {err_txt}")
                            break
                            
                        data = await resp.json()
                        if 'candidates' not in data or not data['candidates']:
                            retry += 1
                            await asyncio.sleep(2)
                            continue
                            
                        text_response = data['candidates'][0]['content']['parts'][0]['text']
                        results = extract_json(text_response)
                        
                        if len(results) != len(batch_indices):
                            if retry < 3:
                                retry += 1
                                await asyncio.sleep(1)
                                continue
                            else:
                                break
                                
                        # Successful Output
                        async with WRITE_LOCK:
                            with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out:
                                for i, idx in enumerate(batch_indices):
                                    original_pair = all_pairs[idx]
                                    code = next(m["content"] for m in original_pair["messages"] if m["role"] == "assistant")
                                    sys_prompt = next(m["content"] for m in original_pair["messages"] if m["role"] == "system")
                                    sharegpt_record = {
                                        "messages": [
                                            {"role": "system", "content": sys_prompt},
                                            {"role": "user", "content": results[i]},
                                            {"role": "assistant", "content": code}
                                        ]
                                    }
                                    f_out.write(json.dumps(sharegpt_record, ensure_ascii=False) + "\\n")
                            
                            PROCESSED_COUNT += len(batch_indices)
                            save_checkpoint(PROCESSED_COUNT, sampled_indices)
                            pbar.update(len(batch_indices))
                            
                        # Add a hard delay between SUCCESSFUL calls to prevent instant spike locks
                        await asyncio.sleep(25 + random.uniform(0, 10))
                        break # exit retry loop
                        
                except Exception as e:
                    print(f"\\n[Worker {worker_id}] Exception: {e}")
                    retry += 1
                    await asyncio.sleep(5)
                    if retry > 10:
                        break
                        
            queue.task_done()

async def async_main():
    global PROCESSED_COUNT
    all_pairs = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_pairs.append(json.loads(line))
                
    total_baseline = len(all_pairs)
    print(f"Loaded {total_baseline} baseline pairs.")
    print(f"Starting with {len(API_KEYS)} API keys! Commencing Threadpool...")
    
    PROCESSED_COUNT, previously_sampled_indices = load_checkpoint()
    
    if previously_sampled_indices:
        sampled_indices = list(previously_sampled_indices)
    else:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
            for pair in all_pairs:
                clean_pair = {"messages": pair["messages"]}
                f_out.write(json.dumps(clean_pair, ensure_ascii=False) + "\n")
        
        val_target = min(TARGET_LLM_SAMPLES, total_baseline)
        sampled_indices = perform_stratified_sampling(all_pairs, val_target)
        save_checkpoint(0, sampled_indices)
        
    remaining_indices = sampled_indices[PROCESSED_COUNT:]
    print(f"Generating paraphrased prompts for {len(remaining_indices)} models...")
    
    queue = asyncio.Queue()
    for i in range(0, len(remaining_indices), BATCH_SIZE):
        queue.put_nowait(remaining_indices[i:i+BATCH_SIZE])
        
    pbar = tqdm(total=TARGET_LLM_SAMPLES, initial=PROCESSED_COUNT, desc="LLM Paraphrasing")
    
    workers = []
    for i, key in enumerate(API_KEYS):
        workers.append(asyncio.create_task(worker(i, key, queue, pbar, all_pairs, sampled_indices)))
        
    await queue.join()
    
    for _ in workers:
        queue.put_nowait(None)
    await asyncio.gather(*workers)
    
    pbar.close()
    print(f"\nFinished hybrid generation! Total file lines: {len(all_pairs) + PROCESSED_COUNT}")
    
def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
