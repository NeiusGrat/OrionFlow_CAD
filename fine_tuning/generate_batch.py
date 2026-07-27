"""Batch-generate Blueprints from a trained checkpoint, offline.

Scoring the model means generating a few hundred completions. Doing that
one-at-a-time over HTTP costs hours on a single GPU; batching it costs minutes,
and the eval harness only needs a completions file anyway (generation happens
where the GPU is, verification where FreeCAD is).

    python fine_tuning/generate_batch.py --adapter runs/orionflow-32b \
        --data sft_v1/test.jsonl --n 200 --out completions.jsonl

Then, on the machine with FreeCAD:

    python -m orion.eval_blueprint --completions completions.jsonl
"""

from __future__ import annotations

try:
    from unsloth import FastLanguageModel          # must precede transformers
    _HAS_UNSLOTH = True
except Exception:                                   # noqa: BLE001
    _HAS_UNSLOTH = False

import argparse
import json
import os
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

IM_START, IM_END = "<|im_start|>", "<|im_end|>"


def build_prompt(messages: list[dict]) -> str:
    """Identical framing to training, stopped at the assistant header."""
    system, user = messages[0], messages[1]
    return (f"{IM_START}{system['role']}\n{system['content']}{IM_END}\n"
            f"{IM_START}{user['role']}\n{user['content']}{IM_END}\n"
            f"{IM_START}assistant\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    # Optional so the base model can be scored as a baseline, and so the
    # generation plumbing can be exercised against a small model without
    # waiting on a checkpoint.
    ap.add_argument("--adapter", default=None,
                    help="LoRA dir or merged model; omit to run --base alone")
    ap.add_argument("--base", default="Qwen/Qwen3-32B")
    ap.add_argument("--data", default="sft_v1/test.jsonl")
    ap.add_argument("--out", default="completions.jsonl")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new-tokens", type=int, default=2560)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-seq", type=int, default=4096)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")][:args.n]
    prompts = [build_prompt(r["messages"]) for r in rows]
    metas = [r["meta"] for r in rows]
    print(f"{len(prompts)} prompts from {args.data}")

    # An adapter dir has adapter_config.json; a merged/plain model has only
    # config.json. Nothing to attach when --adapter is omitted.
    merged = bool(args.adapter) and \
        os.path.exists(os.path.join(args.adapter, "config.json")) and \
        not os.path.exists(os.path.join(args.adapter, "adapter_config.json"))
    attach = bool(args.adapter) and not merged
    source = args.adapter if merged else args.base
    print(f"loading {source}" + (f" + adapter {args.adapter}" if attach else ""))

    if _HAS_UNSLOTH:
        model, tok = FastLanguageModel.from_pretrained(
            model_name=source, max_seq_length=args.max_seq,
            dtype=torch.bfloat16, load_in_4bit=False)
        if attach:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, args.adapter)
        FastLanguageModel.for_inference(model)
    else:
        tok = AutoTokenizer.from_pretrained(source)
        model = AutoModelForCausalLM.from_pretrained(
            source, torch_dtype=torch.bfloat16, device_map="auto")
        if attach:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, args.adapter)
        model.eval()

    # Generation pads on the LEFT: right padding puts pad tokens between the
    # prompt and the first generated token, and the model continues from the
    # padding instead of from the assistant header.
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    eos_id = tok.convert_tokens_to_ids(IM_END)

    done, t0 = [], time.time()
    for i in range(0, len(prompts), args.batch_size):
        chunk = prompts[i:i + args.batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True,
                  truncation=True, max_length=args.max_seq).to(model.device)
        with torch.no_grad():
            out = model.generate(
                **enc, max_new_tokens=args.max_new_tokens,
                do_sample=args.temperature > 0,
                temperature=args.temperature if args.temperature > 0 else None,
                eos_token_id=eos_id, pad_token_id=tok.pad_token_id)
        for j in range(len(chunk)):
            gen = out[j][enc["input_ids"].shape[1]:]
            done.append(tok.decode(gen, skip_special_tokens=True))
        el = time.time() - t0
        print(f"  {len(done)}/{len(prompts)}  {el:.0f}s  "
              f"({el / max(len(done), 1):.1f}s/sample)")

    # Keep the originating system+user turns alongside the completion: a repair
    # round has to show the model its own attempt in context, and the verifier
    # runs on a different machine that never saw the prompt.
    with open(args.out, "w", encoding="utf-8") as fh:
        for completion, meta, row in zip(done, metas, rows):
            fh.write(json.dumps({
                "completion": completion,
                "meta": meta,
                "messages": [m for m in row["messages"] if m["role"] != "assistant"],
            }) + "\n")
    print(f"wrote {args.out} ({len(done)} completions in "
          f"{time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
