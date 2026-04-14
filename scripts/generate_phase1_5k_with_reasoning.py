import json
import random
import os
import sys

target_folder = 'e:/OrionFLow_CAD/data/phase1_5k'
os.makedirs(target_folder, exist_ok=True)
input_train = 'e:/OrionFLow_CAD/data/final_training_dataset/train.jsonl'
input_val = 'e:/OrionFLow_CAD/data/final_training_dataset/val.jsonl'
input_test = 'e:/OrionFLow_CAD/data/final_training_dataset/test.jsonl'

def generate_reasoning_trace(sample):
    source = sample.get('source', '')
    complexity = sample.get('complexity', 1)
    edit_type = sample.get('edit_type', '')
    
    if 'edit' in source or edit_type in ['add_feature', 'param_change', 'multi_edit', 'delete_feature']:
        return "<think>\n1. Understand request: Modify the part based on the user's prompt while preserving the FTC structure.\n2. Identify minimal change: The change requested is an " + str(edit_type) + " edit.\n3. Apply modification: I will only insert/modify the required parameters and the specific Feature step.\n4. Verify structure: Ensure `from build123d import *` and `export_step(result, 'output.step')` are present and the code remains byte-identical elsewhere.\n</think>\n"
    else:
        return "<think>\n1. Understand request: Design an object that conforms to the user's specifications.\n2. Plan Feature Tree: Identify the sequence of BuildPart, BuildSketch, and extrusion/cutting operations required.\n3. Define parameters: Extract magic numbers into explicitly named parameters at the top.\n4. Generate code: Write the valid Build123d FTC code, ensuring valid geometry.\n5. Verify structure: Ensure imports and export remain correct.\n</think>\n"


all_samples = []

for file_path in [input_train, input_val, input_test]:
    with open(file_path, 'r', encoding='utf-8') as file:
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
    
    if 'edit' in source or edit_type in ['add_feature', 'param_change', 'multi_edit', 'delete_feature']:
        edit_samples.append(data)
    elif source in ['template', 'complex_generated', 'deepcad'] or edit_type is None:
        gen_samples.append(data)

random.seed(42)
random.shuffle(edit_samples)
random.shuffle(gen_samples)

num_edits = min(3000, len(edit_samples))
num_gens = min(2000, len(gen_samples))

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

# Add reasoning traces to ~25%
reasoning_samples_p = random.sample(final_dataset, int(len(final_dataset) * 0.25))

for sample in final_dataset:
    if sample in reasoning_samples_p:
       msgs = sample.get('messages', [])
       for msg in msgs:
           if msg.get('role') == 'assistant':
               old_content = msg.get('content', '')
               new_content = generate_reasoning_trace(sample) + old_content
               msg['content'] = new_content

random.shuffle(final_dataset)

out_path = os.path.join(target_folder, 'phase1_perfect_5k.jsonl')
with open(out_path, 'w', encoding='utf-8') as out_f:
    for item in final_dataset:
        out_f.write(json.dumps(item) + '\n')

print(f"Generating Reasoning traces complete! Total size: {len(final_dataset)}")
print(f"Added reasoning to {len(reasoning_samples_p)} samples.")
