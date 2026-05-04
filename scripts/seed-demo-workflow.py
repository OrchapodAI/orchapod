"""
scripts/seed-demo-workflow.py

Seeds the database with the canonical demo workflow used for the YC application video.
Run once after `docker compose up` to have a ready-to-run demo.

Demo: Fine-tune Qwen3-4B on Dolly, distill to 1.7B, quantize for Ollama + vLLM,
      evaluate all three, serve the AWQ model. Target cost: under $5 on Vast.ai.

Usage:
  python scripts/seed-demo-workflow.py
"""

import httpx
import json

API_URL = "http://localhost:8000"

DEMO_WORKFLOW_YAML = """
name: "qwen3-finetune-distill-quantize-deploy"
version: 1

inputs:
  dataset_uri:
    type: string
    description: "JSONL or HF dataset"
    default: "argilla/databricks-dolly-15k-curated-en"
  base_model:
    type: string
    default: "Qwen/Qwen3-4B-Instruct"

nodes:
  - id: prep
    type: data-prep
    inputs:
      dataset: ${{ inputs.dataset_uri }}
      format: chatml
      train_split: 0.9

  - id: train
    type: unsloth-train
    needs: [prep]
    inputs:
      model: ${{ inputs.base_model }}
      train_data: ${{ nodes.prep.outputs.train_jsonl }}
      eval_data: ${{ nodes.prep.outputs.eval_jsonl }}
      lora_r: 16
      lora_alpha: 32
      max_steps: 500
      learning_rate: 0.0002
    resources:
      gpu: "1xH100"
      provider_pref: ["runpod", "vastai"]

  - id: distill
    type: distill-sft
    needs: [train]
    inputs:
      teacher: ${{ nodes.train.outputs.merged_model }}
      student_base: "Qwen/Qwen3-1.7B-Instruct"
      train_data: ${{ nodes.prep.outputs.train_jsonl }}
      n_synthetic: 5000
    resources:
      gpu: "1xH100"

  - id: quant_gguf
    type: quantize
    needs: [distill]
    inputs:
      model: ${{ nodes.distill.outputs.student_model }}
      method: gguf
      precision: q4_k_m

  - id: quant_awq
    type: quantize
    needs: [distill]
    inputs:
      model: ${{ nodes.distill.outputs.student_model }}
      method: awq
      bits: 4
    resources:
      gpu: "1xH100"

  - id: eval
    type: lm-eval
    needs: [train, distill]
    inputs:
      models:
        - ${{ inputs.base_model }}
        - ${{ nodes.train.outputs.merged_model }}
        - ${{ nodes.distill.outputs.student_model }}
      tasks: [hellaswag, mmlu_stem, gsm8k]
      judge_eval_set: ${{ nodes.prep.outputs.eval_jsonl }}
    resources:
      gpu: "1xH100"

  - id: deploy
    type: vllm-serve
    needs: [quant_awq, eval]
    inputs:
      model: ${{ nodes.quant_awq.outputs.awq_model }}
      max_model_len: 8192
      keep_alive_min: 60
    resources:
      gpu: "1xH100"
      provider_pref: ["runpod", "vastai"]
""".strip()


def seed():
    resp = httpx.post(f"{API_URL}/api/workflows", json={
        "name": "YC Demo: Qwen3-4B → distill → quantize → serve",
        "yaml": DEMO_WORKFLOW_YAML,
    })
    resp.raise_for_status()
    workflow = resp.json()
    print(f"Created workflow: {workflow['id']}")
    print(f"Open: http://localhost:3000/canvas/{workflow['id']}")


if __name__ == "__main__":
    seed()
