import json
import time
import sys
from orionflow_ofl.data_pipeline.validator import OFLValidator

def main():
    try:
        with open("data/training/synthetic_10k.jsonl") as f:
            pairs = [json.loads(line) for line in f]
        print(f"Loaded {len(pairs)} pairs.")
    except Exception as e:
        print(f"Error loading file: {e}")
        sys.exit(1)

    validator = OFLValidator()
    
    start_time = time.time()
    for i in range(10):
        res = validator.validate(pairs[i]["code"])
        if not res["valid"]:
            print(f"Failed at {i}: {res['errors']}")
    elapsed = time.time() - start_time
    print(f"Time for 10 items: {elapsed:.2f} seconds. Estimated for 9323 items: {(elapsed/10)*9323/60:.2f} minutes.")

if __name__ == "__main__":
    main()
