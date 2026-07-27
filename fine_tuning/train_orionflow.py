"""Fine-tune a Blueprint-authoring CAD model. Qwen3-32B LoRA on one MI300X.

Target: prompt -> ``<think>`` derivation ``</think>`` + Blueprint JSON, where the
JSON round-trips through ``Blueprint.freeze() -> resolve() -> FreeCAD``. Loss is
taken on the assistant turn only; the model is being taught to *author a
contract*, not to paraphrase the request back.

Written against the stack actually shipped on the AMD "Unsloth Studio" image
(trl 0.23.1, transformers 4.57.6, peft 0.18.1, torch 2.11+rocm7.2, unsloth
2026.7.5), which differs from older TRL in ways that fail *silently*:

* ``max_seq_length`` moved to ``SFTConfig.max_length``. Passing the old name is
  ignored and the default (1024) truncates every sample mid-JSON.
* ``DataCollatorForCompletionOnlyLM`` was removed. Prompt masking is now a
  config flag, and without it loss is taken over the prompt too.

Both are handled by feeding TRL a **prompt-completion** dataset and setting
``completion_only_loss=True``: TRL masks the prompt for us, while the ChatML
frame stays hand-built (Qwen3's packaged template rewrites assistant turns and
injects its own empty ``<think>`` pair, which would fight our real ones).

A *full* fine-tune of 32B needs ~512 GB of optimiser state and is impossible on
one 192 GB card — LoRA is not a preference here, it is the only option.

    # smoke test first — always
    python fine_tuning/train_orionflow.py --max-samples 200 --epochs 1 \
        --out runs/smoke

    # real run
    python fine_tuning/train_orionflow.py --out runs/orionflow-32b

    # merge adapters for serving
    python fine_tuning/train_orionflow.py --merge-only runs/orionflow-32b \
        --out runs/merged
"""

from __future__ import annotations

import os as _os

# Must be set before torch is imported (unsloth pulls it in below). The 32B
# weights plus long-sequence activations fragment the heap badly — a real run
# showed 23 GB reserved-but-unallocated at the moment it OOMed. Expandable
# segments let the allocator grow a block instead of hunting for a contiguous
# one. ROCm reads the HIP name; the CUDA name is kept for forward compat.
_os.environ.setdefault("PYTORCH_HIP_ALLOC_CONF", "expandable_segments:True")
_os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Unsloth patches transformers/trl at import time and MUST land before either
# of them, or the patches silently do nothing.
try:
    from unsloth import FastLanguageModel
    _HAS_UNSLOTH = True
except Exception:                                    # noqa: BLE001
    _HAS_UNSLOTH = False

import argparse
import json
import os

import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer

IM_START, IM_END = "<|im_start|>", "<|im_end|>"

DEFAULT_MODEL = "Qwen/Qwen3-32B"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "forge", "sft_v1")


def to_prompt_completion(messages: list[dict]) -> dict:
    """Split a sample into the ChatML prompt and the assistant continuation.

    The prompt ends exactly at the assistant header, so TRL's prompt mask lines
    up with the token where generation begins at inference.
    """
    system, user, assistant = messages[0], messages[1], messages[2]
    prompt = (f"{IM_START}{system['role']}\n{system['content']}{IM_END}\n"
              f"{IM_START}{user['role']}\n{user['content']}{IM_END}\n"
              f"{IM_START}assistant\n")
    completion = f"{assistant['content']}{IM_END}"
    return {"prompt": prompt, "completion": completion}


def load_split(path: str, max_samples: int | None) -> Dataset:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rows.append(to_prompt_completion(json.loads(line)["messages"]))
            if max_samples and len(rows) >= max_samples:
                break
    return Dataset.from_list(rows)


def merge_only(adapter_dir: str, out_dir: str, base: str) -> None:
    """Fold LoRA into the base weights so any server can load a plain model."""
    from peft import PeftModel
    print(f"merging {adapter_dir} into {base}")
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.bfloat16, device_map="cpu")
    model = PeftModel.from_pretrained(model, adapter_dir)
    model = model.merge_and_unload()
    model.save_pretrained(out_dir, safe_serialization=True)
    AutoTokenizer.from_pretrained(adapter_dir).save_pretrained(out_dir)
    print(f"merged model -> {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--out", default="runs/orionflow-32b")
    ap.add_argument("--epochs", type=float, default=2.0)
    # batch 4 OOMs on a 192 GB card: group_by_length deliberately batches the
    # longest samples together, so the peak step is 4 x ~3000 tokens of logits
    # over a 152k vocab, not the average. 2 x 8 keeps the same effective batch
    # of 16 at half the peak.
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    # Longest real sample is 3026 tokens; 4096 only bought unused headroom that
    # the allocator still had to reserve.
    ap.add_argument("--max-seq", type=int, default=3072)
    ap.add_argument("--lora-r", type=int, default=64)
    ap.add_argument("--lora-alpha", type=int, default=128)
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--eval-samples", type=int, default=200)
    ap.add_argument("--save-steps", type=int, default=200)
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "unsloth", "hf"])
    ap.add_argument("--attn", default="sdpa",
                    choices=["sdpa", "flash_attention_2", "eager"])
    ap.add_argument("--no-group-by-length", action="store_true")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--merge-only", default=None)
    args = ap.parse_args()

    if args.merge_only:
        merge_only(args.merge_only, args.out, args.model)
        return

    use_unsloth = args.backend == "unsloth" or (
        args.backend == "auto" and _HAS_UNSLOTH)
    print(f"torch {torch.__version__} | HIP {torch.version.hip} | "
          f"GPUs {torch.cuda.device_count()} | "
          f"backend {'unsloth' if use_unsloth else 'hf'}")

    train_ds = load_split(os.path.join(args.data_dir, "train.jsonl"),
                          args.max_samples)
    eval_ds = load_split(os.path.join(args.data_dir, "val.jsonl"),
                         args.eval_samples)
    print(f"train {len(train_ds)} | val {len(eval_ds)}")

    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"]

    peft_config = None
    if use_unsloth:
        model, tok = FastLanguageModel.from_pretrained(
            model_name=args.model,
            max_seq_length=args.max_seq,
            dtype=torch.bfloat16,
            load_in_4bit=False,          # 192 GB — no need to quantise
            full_finetuning=False,
        )
        model = FastLanguageModel.get_peft_model(
            model, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0,
            bias="none", target_modules=target_modules,
            use_gradient_checkpointing="unsloth", random_state=1602)
    else:
        from peft import LoraConfig
        tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=torch.bfloat16, trust_remote_code=True,
            attn_implementation=args.attn)
        model.config.use_cache = False
        peft_config = LoraConfig(
            r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
            bias="none", task_type="CAUSAL_LM",
            target_modules=target_modules)

    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"

    from trl import SFTConfig, SFTTrainer
    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        max_grad_norm=1.0,
        bf16=True,
        logging_steps=10,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=4,
        eval_strategy="steps",
        eval_steps=args.save_steps,
        per_device_eval_batch_size=1,
        optim="adamw_torch_fused",
        report_to="none",
        seed=1602,
        # ---- the three that silently break if wrong ---------------------- #
        max_length=args.max_seq,          # NOT max_seq_length on trl>=0.20
        completion_only_loss=True,        # replaces the removed collator
        packing=False,                    # packing would defeat prompt masking
        # ------------------------------------------------------------------ #
        # Samples run ~1.2k-3.2k tokens; batching at random pads nearly every
        # batch up to its longest member and burns compute on padding. This is
        # the cheapest real speedup on a single GPU, which is where this run is
        # throughput-bound.
        group_by_length=not args.no_group_by_length,
        # LoRA freezes most of the network, and DDP's unused-parameter scan
        # both costs time and trips on the frozen graph.
        ddp_find_unused_parameters=False,
        # Unsloth installs its own checkpointing; letting HF also enable it
        # double-wraps the modules.
        gradient_checkpointing=not use_unsloth,
        gradient_checkpointing_kwargs=(None if use_unsloth
                                       else {"use_reentrant": False}),
    )

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=train_ds,
                         eval_dataset=eval_ds, processing_class=tok,
                         peft_config=peft_config)

    # Prove the mask before burning hours on it: the prompt must be excluded
    # from the labels and the assistant turn must survive intact.
    batch = trainer.data_collator([trainer.train_dataset[i] for i in range(2)])
    labels = batch["labels"][0]
    kept = int((labels != -100).sum())
    print(f"mask check: {kept}/{len(labels)} tokens supervised "
          f"({100.0 * kept / len(labels):.0f}% — expect the assistant turn only)")
    shown = tok.decode([t for t in labels if t != -100][:40])
    print(f"first supervised tokens: {shown!r}")

    trainer.train(resume_from_checkpoint=args.resume)
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"adapters -> {args.out}")


if __name__ == "__main__":
    main()
