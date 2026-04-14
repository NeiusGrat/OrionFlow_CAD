import json
import random
import os

target_folder = 'e:/OrionFLow_CAD/data/phase1_5k'
os.makedirs(target_folder, exist_ok=True)
input_train = 'e:/OrionFLow_CAD/data/final_training_dataset/train.jsonl'
input_val = 'e:/OrionFLow_CAD/data/final_training_dataset/val.jsonl'
input_test = 'e:/OrionFLow_CAD/data/final_training_dataset/test.jsonl'

all_samples = []

for file_path in [input_train, input_val, input_test]:
    with open(file_path, 'r') as file:
        for line in file:
            data = json.loads(line)
            val = data.get('_validation', {})
            # Only keep passed samples that did not fail any stage
            if not val.get('passed'): continue
            if val.get('stage_failed'): continue
            
            source = data.get('source', '')
            edit_type = data.get('edit_type')
            
            # Filter out refusal/synthetic failure templates, only want pure clean editing/generation
            if source.startswith('phase5') or source == 'synthetic_refusal':
                continue
                
            all_samples.append(data)

edit_samples = []
gen_samples = []

for data in all_samples:
    source = data.get('source', '')
    edit_type = data.get('edit_type')
    
    # Minimal diff enforce flag could be added here if needed, but since these passed validation,
    # they are already deemed good code.
    
    if 'edit' in source or edit_type in ['add_feature', 'param_change', 'multi_edit', 'delete_feature']:
        edit_samples.append(data)
    elif source in ['template', 'complex_generated', 'deepcad'] or edit_type is None:
        gen_samples.append(data)

random.seed(42)
random.shuffle(edit_samples)
random.shuffle(gen_samples)

print(f'Total Valid edit samples: {len(edit_samples)}')
print(f'Total Valid generation samples: {len(gen_samples)}')

# Target ~60% editing samples (3000), ~40% generation samples (2000)
# Total 5000 max

num_edits = min(3000, len(edit_samples))
num_gens = min(2000, len(gen_samples))

# If we don't have enough generation samples but have extra edit samples, backfill (though we have enough)
if num_edits + num_gens < 5000:
    diff = 5000 - (num_edits + num_gens)
    if len(edit_samples) > 3000:
        extra_edits = min(diff, len(edit_samples) - 3000)
        num_edits += extra_edits
    if len(gen_samples) > 2000:
        diff = 5000 - (num_edits + num_gens)
        extra_gens = min(diff, len(gen_samples) - 2000)
        num_gens += extra_gens

final_dataset = edit_samples[:num_edits] + gen_samples[:num_gens]
random.shuffle(final_dataset)

# Optional: Adding small 50-100 sample recovery data
# For now the script takes 5000 perfect samples.
print(f"Selecting {num_edits} edit samples and {num_gens} generation samples. Total: {len(final_dataset)}")

out_path = os.path.join(target_folder, 'phase1_perfect_5k.jsonl')
with open(out_path, 'w') as out_f:
    for item in final_dataset:
        out_f.write(json.dumps(item) + '\n')

print(f"Saved to {out_path}")
