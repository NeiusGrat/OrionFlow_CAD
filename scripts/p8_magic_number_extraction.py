import json
import re
import collections
from pathlib import Path

def process_inline_numbers(code: str):
    lines = code.splitlines()
    param_idx = -1
    tree_idx = -1
    
    for i, line in enumerate(lines):
        if '# --- Parameters ---' in line:
            param_idx = i
        if '# --- Feature Tree ---' in line:
            tree_idx = i
            
    if param_idx == -1 or tree_idx == -1:
        return code, False
        
    param_counters = collections.defaultdict(int)
    new_params = []
    
    def repl_circle(m):
        val = m.group(2)
        param_counters['circle_radius'] += 1
        pname = f"circle_radius_{param_counters['circle_radius']}"
        new_params.append(f"{pname} = {val}  # mm")
        return f"{m.group(1)}{pname}{m.group(3)}"
        
    def repl_rect_both(m):
        w, h = m.group(2), m.group(4)
        param_counters['rect_width'] += 1
        param_counters['rect_height'] += 1
        pw = f"rect_width_{param_counters['rect_width']}"
        ph = f"rect_height_{param_counters['rect_height']}"
        new_params.append(f"{pw} = {w}  # mm")
        new_params.append(f"{ph} = {h}  # mm")
        return f"{m.group(1)}{pw}{m.group(3)}{ph}{m.group(5)}"

    def repl_extrude(m):
        val = m.group(2)
        param_counters['extrude_depth'] += 1
        pname = f"extrude_depth_{param_counters['extrude_depth']}"
        new_params.append(f"{pname} = {val}  # mm")
        return f"{m.group(1)}{pname}{m.group(3)}"
        
    def repl_fillet(m):
        val = m.group(2)
        param_counters['fillet_radius'] += 1
        pname = f"fillet_radius_{param_counters['fillet_radius']}"
        new_params.append(f"{pname} = {val}  # mm")
        return f"{m.group(1)}{pname}{m.group(3)}"

    modified = False
    for i in range(tree_idx + 1, len(lines)):
        if lines[i].strip().startswith('#'): 
            continue
            
        old_line = lines[i]
        
        lines[i] = re.sub(r'(Circle\s*\(\s*(?:radius\s*=\s*)?)(\d+\.?\d*)(\s*\))', repl_circle, lines[i])
        lines[i] = re.sub(r'(Rectangle\s*\(\s*(?:width\s*=\s*)?)(\d+\.?\d*)(\s*,\s*(?:height\s*=\s*)?)(\d+\.?\d*)(\s*\))', repl_rect_both, lines[i])
        
        # for extrude, fillet, we use a negative lookbehind/lookahead to only match digits, not part of variable names
        # m.group(1) is prologue, m.group(2) is digits, m.group(3) is rest.
        lines[i] = re.sub(r'(extrude\s*\([^)]*(?:amount\s*=\s*)-?)(\d+\.?\d*)(\b)', repl_extrude, lines[i])
        lines[i] = re.sub(r'(fillet\s*\([^)]*(?:radius\s*=\s*))(\d+\.?\d*)(\b)', repl_fillet, lines[i])
        
        if lines[i] != old_line:
            modified = True

    if modified and new_params:
        lines.insert(param_idx + 1, '\n'.join(new_params))
        return '\n'.join(lines), True
    return code, False

if __name__ == '__main__':
    splits = ["train", "val", "test"]
    total_mod = 0
    
    for split in splits:
        fpath = Path(f"data/final_training_dataset/{split}.jsonl")
        if not fpath.exists(): continue
        
        records = []
        mod_count = 0
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                rec = json.loads(line)
                
                asst_idx = next(i for i, m in enumerate(rec['messages']) if m['role'] == 'assistant')
                content = rec['messages'][asst_idx]['content']
                
                has_md = False
                if '```python' in content:
                    has_md = True
                    prefix, code_block = content.split('```python\n', 1)
                    code, suffix = code_block.split('\n```', 1)
                else:
                    code = content
                    
                new_code, modified = process_inline_numbers(code)
                
                if modified:
                    mod_count += 1
                    total_mod += 1
                    if has_md:
                        rec['messages'][asst_idx]['content'] = f"{prefix}```python\n{new_code}\n```{suffix}"
                    else:
                        rec['messages'][asst_idx]['content'] = new_code
                        
                records.append(rec)
                
        if mod_count > 0:
            with open(fpath, 'w', encoding='utf-8') as f:
                for rec in records:
                    f.write(json.dumps(rec) + '\n')
        print(f"[{split}] Modified {mod_count} records.")
        
    print(f"Total records safely parameterized: {total_mod}")
