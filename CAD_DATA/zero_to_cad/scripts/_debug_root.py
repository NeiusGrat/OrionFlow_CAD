"""Find samples failing 'chain root not Workplane' and show their roots."""
import ast
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad")
b123d = [json.loads(l) for l in (ROOT / "b123d" / "validation.jsonl").open(encoding="utf-8")]
raw = {}
for line in (ROOT / "raw" / "validation.jsonl").open(encoding="utf-8"):
    r = json.loads(line)
    raw[r["uuid"]] = r["code"]

failing = [r for r in b123d if "chain root not Workplane" in r["reason"]]
print(f"failing root: {len(failing)}")
shown = 0
for r in failing[:30]:
    code = raw[r["uuid"]]
    try:
        tree = ast.parse(code)
    except SyntaxError:
        continue
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            # Walk to root
            cur = n.value
            while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                cur = cur.func.value
            if isinstance(cur, ast.Call):
                root_func = cur.func
                if isinstance(root_func, ast.Attribute):
                    val = root_func.value
                    inner = val.id if isinstance(val, ast.Name) else type(val).__name__
                    rstr = f"{inner}.{root_func.attr}"
                else:
                    rstr = ast.unparse(root_func) if hasattr(ast, 'unparse') else str(root_func)
                if rstr not in ("cq.Workplane", "Workplane"):
                    target = n.targets[0].id if isinstance(n.targets[0], ast.Name) else "?"
                    print(f"  uuid={r['uuid'][:8]}  {target} = ... root={rstr}")
                    shown += 1
                    break
    if shown >= 25:
        break
