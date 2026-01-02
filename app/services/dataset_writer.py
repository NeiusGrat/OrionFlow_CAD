import json
import os
from datetime import datetime
from app.domain.dataset_sample import DatasetSample


DATASET_ROOT = "data/dataset"


def write_dataset_sample(sample: DatasetSample):
    status_dir = "success" if sample.success else "failure"
    target_dir = os.path.join(DATASET_ROOT, status_dir)
    os.makedirs(target_dir, exist_ok=True)

    # Windows-safe filename: replace : with -
    timestamp_str = sample.timestamp.replace(":", "-")
    # Adding prompt snippet for easier debugging/browsing
    safe_prompt = "".join([c if c.isalnum() else "_" for c in sample.prompt[:20]])
    filename = f"{timestamp_str}_{safe_prompt}.json"
    filepath = os.path.join(target_dir, filename)

    try:
        with open(filepath, "w") as f:
            json.dump(sample.model_dump(), f, indent=2)
    except Exception as e:
        print(f"Failed to write dataset sample: {e}")
