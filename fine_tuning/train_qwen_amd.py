import os
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    DataCollatorForLanguageModeling
)
from trl import SFTTrainer
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

# ==========================================
# HYPERPARAMETERS & CONFIG (AMD MI300X 192GB VRAM)
# ==========================================

MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
DATASET_PATH = "../data/training/ofl_finetune_data_hybrid.jsonl"
OUTPUT_DIR = "./qwen2.5-coder-7b-ofl-lora"

# With 192GB VRAM, we don't need 4-bit quantization! We can train in pure bf16 natively.
# This is much faster on AMD ROCm and yields slightly better accuracy.
USE_BFLOAT16 = True  

# LoRA Config
LORA_R = 64          # High rank because we have the VRAM
LORA_ALPHA = 128
LORA_DROPOUT = 0.05
# Target modules for Qwen architectures
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"] 

# Training Args
BATCH_SIZE = 8       # Increased batch size due to massive VRAM
GRAD_ACCUM_STEPS = 4 # Effective Batch Size: 32
MAX_SEQ_LENGTH = 2048
LEARNING_RATE = 2e-5
EPOCHS = 3           # Start with 3 epochs on the 54k dataset

def main():
    print(f"🚀 Initializing Phase 6 Fine-Tuning Pipeline for native AMD ROCm...")
    print(f"🔌 PyTorch version: {torch.__version__}")
    print(f"🖥️  HIP/ROCm available: {'Yes' if torch.version.hip else 'No'}")
    
    # 1. Load Tokenizer
    print(f"Loading Tokenizer: {MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    
    # 2. Load Dataset
    print(f"Loading Dataset: {DATASET_PATH}")
    # We use our custom hybrid jsonl dataset here
    dataset = load_dataset("json", data_files=DATASET_PATH, split="train")
    print(f"Loaded {len(dataset)} training examples.")
    
    # 3. Format Dataset (ChatML)
    def apply_chat_template(example):
        messages = example["messages"]
        # The Qwen tokenizer has a built-in `apply_chat_template` that converts our
        # standard "system, user, assistant" list into pure Qwen ChatML string format.
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    print("Applying ChatML formatting to the dataset...")
    dataset = dataset.map(apply_chat_template, num_proc=8)

    # 4. Load Model 
    # Notice we load in bfloat16 directly, bypassing load_in_4bit since we have 192GB VRAM
    print(f"Loading Base Model: {MODEL_ID} in bfloat16")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        # FA2 is natively supported on ROCm 6.0+ via PyTorch 2.6
        attn_implementation="flash_attention_2" 
    )
    
    # 5. Setup LoRA
    print("Injecting LoRA adapters...")
    peft_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=TARGET_MODULES,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # 6. Training Arguments
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM_STEPS,
        learning_rate=LEARNING_RATE,
        logging_steps=10,
        save_strategy="epoch",
        bf16=USE_BFLOAT16,            # AMD MI300X favors BFloat16 heavily
        optim="adamw_torch_fused",    # Standard optimizer
        max_grad_norm=0.3,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        report_to="none",             # 'wandb' if you have an account
        gradient_checkpointing=True   # Save memory, though we have plenty
    )

    # 7. Start Trainer
    print("Initializing SFT Trainer...")
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        dataset_text_field="text",    # Output of our chat_template mapper
        max_seq_length=MAX_SEQ_LENGTH,
        tokenizer=tokenizer,
        args=training_args,
    )

    print("🔥 Starting Training Protocol...")
    trainer.train()

    # 8. Save Model
    print(f"✅ Training Complete. Saving LoRA adapters to {OUTPUT_DIR}")
    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

if __name__ == "__main__":
    main()
