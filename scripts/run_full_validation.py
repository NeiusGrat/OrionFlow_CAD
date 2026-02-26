import json
import time
import sys
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from orionflow_ofl.data_pipeline.validator import OFLValidator

def validate_pair(idx, pair):
    validator = OFLValidator()
    res = validator.validate(pair["code"])
    return idx, res

def main():
    try:
        with open("data/training/synthetic_10k.jsonl") as f:
            pairs = [json.loads(line) for line in f]
        print(f"Loaded {len(pairs)} pairs.")
    except Exception as e:
        print(f"Error loading file: {e}")
        sys.exit(1)

    workers = multiprocessing.cpu_count()
    print(f"Starting validation with {workers} workers on {len(pairs)} items...")

    start_time = time.time()
    valid_count = 0
    invalid_count = 0
    invalid_indices = []

    # Checkpoint logic
    results_file = "data/training/validation_results.json"
    processed = {}
    if os.path.exists(results_file):
        with open(results_file) as f:
            processed = json.load(f)
            print(f"Resuming from {len(processed)} previously validated items.")

    to_process = [(i, p) for i, p in enumerate(pairs) if str(i) not in processed]
    
    # We will just process a sample of 200 items for a quick test if full validation is too slow, 
    # but the user requested checking the remaining. We will run it on all remaining, tracking progress.
    
    print(f"Items left to validate: {len(to_process)}")

    completed = len(processed)

    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(validate_pair, i, p): (i, p) for i, p in to_process}
            
            for future in as_completed(futures):
                idx, res = future.result()
                processed[str(idx)] = res
                
                if res["valid"]:
                    valid_count += 1
                else:
                    invalid_count += 1
                    invalid_indices.append(idx)
                    
                completed += 1
                
                if completed % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = (completed - len(processed) + len(to_process) - len(futures)) / elapsed if elapsed > 0 else 1
                    rate = max(rate, 0.001)
                    rem_time = (len(pairs) - completed) / rate
                    print(f"Progress: {completed}/{len(pairs)} | Valid: {valid_count} | Invalid: {invalid_count} | Elapsed: {elapsed:.1f}s | Est. Rem: {rem_time/60:.1f}m")
                    
                    # Save checkpoint
                    with open(results_file, 'w') as f:
                        json.dump(processed, f)

    except KeyboardInterrupt:
        print("Interrupted! Saving results...")
        
    finally:
        with open(results_file, 'w') as f:
            json.dump(processed, f)

        # Final count
        v_count = sum(1 for v in processed.values() if v.get("valid", False))
        iv_count = len(processed) - v_count
        
        print("\n=== Validation Report ===")
        print(f"Total processed: {len(processed)}")
        print(f"Valid: {v_count}")
        print(f"Invalid: {iv_count}")
        if iv_count > 0:
            print("Invalid examples index list:")
            print([k for k, v in processed.items() if not v.get("valid", False)])

if __name__ == "__main__":
    main()
