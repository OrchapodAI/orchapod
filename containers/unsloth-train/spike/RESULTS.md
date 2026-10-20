# Spike 4: Lane B student (Unsloth 16-bit LoRA → 16-bit merge → vLLM), 2026-10-20

These numbers come from a rented vast.ai GPU. They are inputs to a decision, not claims about Nebius.

## Instance and cost
- vast.ai offer 49739788 → instance 56963420: 1× **A100-SXM4-80GB**, driver 595.71.05, Japan, verified, reliability 0.9953, 220 GB disk, 128 vCPU.
- **$1.2485/h** (GPU $1.1467 + 220 GB storage at $0.333/GB/month); download bandwidth $0.004/GB.
- Created 22:54:51Z, destroyed 23:43:38Z (watchdog trap): **48 min 47 s**.
- **Total ≈ $1.29.** Account credit fell by $1.341 between 22:54:29Z and 23:45:39Z. About $0.047 of that is storage on two pre-existing stopped instances that are not part of this spike. The rest is GPU and storage ($1.02) plus about $0.28 of download bandwidth.
- The image was `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel` (cached on the host; running 30 s after create). Packages were installed into one uv venv from `requirements.lock.txt`: 203 pins, matched exactly by `uv pip freeze` on the host. The main pins are torch 2.10.0 (cu128), unsloth/unsloth_zoo 2026.10.7, vllm 0.18.0 (the vllm-serve spec's version), transformers 4.57.6, trl 1.15.0 and peft 0.21.2.
- Scripts:
  - `vast.sh`: rent, the watchdog whose EXIT trap destroys the instance, ssh, destroy.
  - `run.sh`: remote driver.
  - `train.py`: LoRA, then merge.
- Data and recipe: the first 200 rows of `yahma/alpaca-cleaned`. LoRA r=16, α=16, batch 2 × gradient accumulation 4, 60 steps, LR 2e-4 linear, adamw_8bit, max_length 1024, bf16, `load_in_4bit=False, load_in_16bit=True`.

## Main run: nvidia/Llama-3.1-Nemotron-Nano-8B-v1 (tag nano8b_v2): PASS
| Phase | Wall time |
| --- | --- |
| Env setup (uv venv, 203 wheels) | 3 min 22 s |
| Model download + load (16 GB) | 66 s (17 s cached) |
| Train, 60 steps (~1.0 s/step) | 62.5 s |
| Merge to 16-bit (4 shards, 15 GB) | 40.5 s |
| vLLM start → /health OK | 51 s (weights 14.99 GiB, KV cache 56 GiB) |
| One chat completion | ~2 s |

- Loss, first 5 steps: 2.405, 2.897, 2.746, 3.126, 2.325. Last 5 steps: 1.266, 0.904, 1.065, 1.293, 1.263.
- Peak training VRAM: 15.9 GiB. Trainable parameters: 41.9 M (0.52%). Unsloth's default target modules were q, k, v, o, gate, up and down.
- Completion (system prompt "detailed thinking off", temperature 0) for "In two sentences, explain what a LoRA adapter is.":
  "A LoRA adapter is a device that allows communication between a LoRaWAN network and a conventional wireless network, such as Wi-Fi or Bluetooth. It translates the LoRaWAN signals into the format used by the conventional network, enabling devices to communicate with each other across different types of wireless networks."
  The model read "LoRA" as LoRa radio. The serving path works; the answer is wrong.

## Stretch: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 (tag nano30b): PASS (train, merge, serve)
- This is the exact HF id (public, 63.2 GB, `NemotronHForCausalLM`, `trust_remote_code`).
- LoRA targets: `.*\.(q_proj|k_proj|v_proj|o_proj|in_proj)|.*\.shared_experts\.(up_proj|down_proj)`.
- Kept frozen:
  - the router (`mixer.gate`: a raw `nn.Parameter`, so LoRA cannot wrap it);
  - the 128 routed experts;
  - Mamba `out_proj` and `conv1d` (PEFT 0.21 refuses LoRA on these).
- The run needs the prebuilt `mamba_ssm 2.3.2.post1` and `causal_conv1d 1.7.0` wheels (cu12, torch 2.10, cp312); no compile.

| Phase | Wall time |
| --- | --- |
| SSM wheels + 63 GB download + load | about 3 min (download ≈ 350 MB/s) |
| Train, 60 steps (88 s first step, then ~11 s/step, GPU ~38% busy) | 746.8 s |
| Merge to 16-bit (13 shards, 59 GB; copies the remote-code files) | 98.7 s |
| vLLM start → /health OK | 76 s (weights 58.91 GiB, KV cache 11.6 GiB = 404,528 tokens, Mamba cache auto float32) |
| First chat completion | ~40 s (probably one-time kernel JIT; warm latency not measured) |

- Loss, first 5 steps: 1.529, 2.100, 1.978, 2.384, 1.674. Last 5 steps: 1.163, 0.929, 0.940, 1.003, 1.154.
- Peak training VRAM: 60.5 GiB (torch). nvidia-smi showed 62,893 MiB during training and 73,619 MiB while serving at `--gpu-memory-utilization 0.9`.
- Completion (`enable_thinking=false`, temperature 0):
  "A LoRA adapter is a lightweight, trainable module that can be added to a pre-trained language model to adapt it to a specific task or domain without modifying the original model's weights. It works by injecting low-rank matrices into the model's weight matrices, allowing for efficient fine-tuning with a small number of parameters."

## Surprises (each fixed in the committed scripts)
1. **BOS.** Unsloth's SFT prep skips `add_special_tokens` when the chat template contains BOS. Run 1 stripped BOS from the text, so it trained with no BOS at all (first-step loss 4.50 → last 1.25). Run 2 kept the template's BOS; its numbers are the ones reported above.
2. **Mamba `out_proj`.** PEFT 0.21 rejects LoRA on Mamba `out_proj` and `conv1d` for `nemotron_h`. The first 30B attempt failed on this after downloading.
3. **apache-tvm-ffi downgrade.** `mamba_ssm` pulls `tilelang`, which downgrades `apache-tvm-ffi` from 0.1.15.post0 to 0.1.9. vLLM's xgrammar import then fails with `load_lib_module() got an unexpected keyword argument 'extra_lib_paths'`. `run.sh` now restores the lock version. A separate vLLM container (vllm-serve) would not hit this.
4. **MoE training speed.** The 30B-A3B trains about 11× slower per step than the 8B (11 s vs 1 s). The HF remote code loops over the 128 experts, and the GPU is about 38% busy.
5. **SSH key.** The account SSH key that matches `~/.ssh/id_ed25519` is passphrase-protected. A throwaway key was attached to this instance only; the account key list is unchanged.
