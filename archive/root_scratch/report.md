# OrionFlow CAD Pipeline: End-to-End Report

This report outlines the complete end-to-end architecture of the OrionFlow ML infrastructure, focusing exclusively on the data synthesis, dataset taxonomy, and the LLM fine-tuning pipeline.

## 1. Codebase Architecture

The OrionFlow repository acts as an end-to-end framework to generate, validate, and train an AI Copilot capable of writing pure parametric CAD models (OFL via Build123d). 

### Core Components
*   **`generate_final_dataset.py` (Data Synthesizer):** The master dataset generator that operates in a multi-stage pipeline:
    1. Generates thousands of synthetic pairs by randomly mutating dimensions of hardcoded Python template classes.
    2. Uses a `TextAnnotator` to write varying plain English descriptions of the generated geometric variations.
    3. Performs automated editing (adding fillets, holes, changing parameter sizes) to create conversational edit-driven multi-turn prompts. 
    4. Validates each snippet by programmatically attempting to compile it, ensuring zero halluciations.
*   **`orionflow_ofl/` (CAD Syntax Wrapper):** Contains Python scripts formatting Build123d into the proprietary OFL string logic format the model expects.
*   **`fine_tuning/train_qwen_amd.py` (SFT Finetuning):** The main training orchestration script designed specifically for Qwen execution on AMD ROCm compute.

## 2. Dataset Taxonomy & Volume

The repository stores numerous iterations of validated generations inside `data/training/`. Current analysis reports **over 60,000 highly validated rows** of instruction-tuned data split across different domains.

### Line Counts & Filenames
*   **`ofl_finetune_data_hybrid.jsonl`:** ~42,576 records *(Primary Source)*
*   **`ofl_finetune_data.jsonl`:** 42,200 records
*   **`synthetic_from_templates.jsonl`:** 30,600 records
*   **`ofl_final_v2.jsonl`:** 15,327 records
*   **`ofl_triaged.jsonl`:** 9,845 records
*   **`training_pairs_v2.jsonl`:** 9,572 records
*   **`editing_pairs.jsonl`:** 5,088 multi-turn editing variations.

## 3. Fine-Tuning Setup and Configuration

The specific setup located in `train_qwen_amd.py` is configured for extremely high memory hardware.

### Environment & Compute
*   **Selected Base Model:** `Qwen/Qwen2.5-Coder-7B-Instruct` (Excels natively in python code structures).
*   **Compute Stack:** Optimized uniquely for **AMD MI300X with 192GB VRAM** running PyTorch ROCm.
*   **Precision:** Pure **bfloat16 (`bf16`)**. With 192GB of available VRAM, standard 4-bit or 8-bit QLoRA quantizations were skipped entirely in favor of native full-precision gradients for higher accuracy. It pairs with *Flash Attention 2*.

### LoRA Hyperparameters (PEFT)
*   `r`: **64** (Operating with large VRAM allows significantly higher expressivity ranks).
*   `lora_alpha`: **128**
*   `lora_dropout`: **0.05**
*   **Target Modules:** Full cross-attention extraction across `["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]`.

### Trainer Hyperparameters
*   **Effective Batch Size:** 32 (8 Per Device * 4 Gradient Accumulation Steps).
*   **Max Sequence Length:** 2048
*   **Learning Rate:** 2e-5 (Cosine Scheduler with 0.03 warmup ratio).
*   **Total Epochs:** 3

## 4. Fine-Tuning Data Sample

All final training data files are packaged precisely in standard ChatML formats that the `transformers` library converts internally using `apply_chat_template`. 

Below is an authentic raw example taken from `ofl_finetune_data_hybrid.jsonl`:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are Orionflow, an expert AI CAD copilot. The user will describe a mechanical part. Your job is to output the pure OFL Python code for that part."
    },
    {
      "role": "user",
      "content": "Generate the OFL script for this mechanical part.\n\nRequirements:\n- It is based on a circular/cylindrical profile that is extruded into 3D. The part features sketching on multiple intersecting planes.\n- Use pure OFL syntax with no markdown wrappers."
    },
    {
      "role": "assistant",
      "content": "from orionflow_ofl import *\n\ndiameter = 0.2\nthickness = 4.1\n\npart = (\n    Sketch(Plane.XZ)\n    .circle(diameter)\n    .extrude(thickness)\n)\nexport(part, \"model.step\")"
    }
  ]
}
```
