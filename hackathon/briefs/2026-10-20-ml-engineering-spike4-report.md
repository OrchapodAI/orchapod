# Report: spike 4, Lane B student (ml-engineering, 2026-10-20)

**Branch** `hack/ml-spike4` (worktree `.claude/worktrees/ml-spike4`, base c866d7f) · **commit** `ba01d91` · **details** `containers/unsloth-train/spike/RESULTS.md`

## Answer
Yes. Unsloth 16-bit LoRA (`load_in_4bit=False`), a 16-bit merge and a vLLM serve all work on one 80 GB GPU, for both Nemotron students. The setup was:
- one vast.ai A100-SXM4-80GB;
- 200 rows of `yahma/alpaca-cleaned`, 60 steps;
- unsloth 2026.10.7, vllm 0.18.0 (the vllm-serve spec's version), torch 2.10.0 cu128;
- one 203-pin lock, verified against `uv pip freeze` on the host.

| | Llama-3.1-Nemotron-Nano-8B-v1 | NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 (stretch) |
| --- | --- | --- |
| Loss, first 5 steps | 2.405 2.897 2.746 3.126 2.325 | 1.529 2.100 1.978 2.384 1.674 |
| Loss, last 5 steps | 1.266 0.904 1.065 1.293 1.263 | 1.163 0.929 0.940 1.003 1.154 |
| Train, 60 steps | 62.5 s (1.0 s/step) | 746.8 s (about 11 s/step) |
| Peak training VRAM | 15.9 GiB | 60.5 GiB |
| Merge to 16-bit | 40.5 s, 15 GB | 98.7 s, 59 GB |
| vLLM start → healthy | 51 s; 15 GiB weights, 56 GiB KV | 76 s; 58.9 GiB weights, 11.6 GiB KV |
| Completion | Wrong: read "LoRA" as LoRa radio (quoted in RESULTS.md) | Correct: "A LoRA adapter is a lightweight, trainable module … injecting low-rank matrices …" |

Other wall times:
- 8B: instance create → running took 30 s (image cached); env setup took 3 min 22 s; the 16 GB download plus load took 66 s.
- 30B: the 63 GB download took about 3 min, and the first completion took about 40 s (probably one-time JIT; warm latency not measured).

Stretch LoRA settings:
- Targets were attention q/k/v/o, Mamba `in_proj`, and the shared experts' up/down.
- Frozen: the router (a raw `nn.Parameter`, which LoRA cannot wrap), the 128 routed experts, and Mamba `out_proj` and `conv1d` (PEFT refuses these).

## Proof
- `bash vast.sh up 49739788 220` → `instance 56963420; watchdog pid 94792; hard stop Tue Oct 20 21:44:51 EDT 2026`
- `SYSTEM="" TARGETS=… bash run.sh nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 nano30b` → `TRAIN_METRICS {… "steps": 60, "peak_vram_gib": 60.5, "train_s": 746.8, "merge_s": 98.7}`, then `PHASE nano30b done`.
- `bash vast.sh down` → watchdog log `destroying instance 56963420.`; `vastai show instances` → `[(54041703, 'rec-l2-bench-2', 'exited'), (54062531, 'esci-bench-v2', 'exited')]`. Those two instances pre-date this spike (stopped since 2026-10-03) and were left untouched; I told the Orchestrator before renting.

## Cost and limits
- The host was a verified A100-SXM4-80GB in Japan at **$1.2485/h** with 220 GB disk. When I re-checked offers it was cheaper than the $1.614/h North Carolina hosts the Orchestrator had approved, and it met even the original $1.60/h sub-limit.
- Lifetime: **48 min 47 s**. **Total ≈ $1.29.** Credit fell by $1.341; $0.047 of that is storage on the two pre-existing stopped instances.
- All caps held: under $6 and 3 h, one instance, the destroy-on-exit watchdog (hard stop at 170 min), and no secrets on the host (both models and the dataset are public, so HF_TOKEN was never needed). No remote step was silent for more than 20 min.
- Account SSH settings were unchanged. The matching account key (`~/.ssh/id_ed25519`) is passphrase-protected, so I attached a throwaway key to this instance only. The key pair has been deleted. Side effect: `~/.ssh/known_hosts` gained one entry, for `[202.122.49.242]:17494`.

## What did not work first time (all fixed in the committed scripts)
1. **BOS.** Unsloth's SFT prep skips `add_special_tokens` when the chat template contains BOS. Run 1 stripped BOS, so it trained without it; its first-step loss was 4.5, and it was discarded. The reported numbers come from run 2.
2. **Mamba `out_proj`.** PEFT 0.21 rejects LoRA on Mamba `out_proj` for `nemotron_h`. This cost one 30B attempt.
3. **apache-tvm-ffi downgrade.** `mamba_ssm` pulls `tilelang`, which downgrades `apache-tvm-ffi`. vLLM's xgrammar import then crashes. `run.sh` restores the lock version before serving. A separate vllm-serve container would not hit this.

## DECISION (proposed)
**Lane B student: `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`**, trained as a 16-bit Unsloth LoRA, merged, and served by vLLM 0.18.0. Reasons:
- Training is 12× faster per step.
- Its 16 GiB training peak and 15 GiB weights fit an L40S, so it is not limited to the H100.
- It needs no extra kernels or dependency pins.
- Artifacts are 4× smaller (15 GB vs 59 GB to move through Object Storage per run).

**Option on record:** Nemotron-3-Nano-30B-A3B is proven feasible on one 80 GB GPU only. It needs the SSM wheels and the tvm-ffi pin, and it cannot be served in bf16 on an L40S. Its better answer here is a single sample; judge-eval should decide quality.

## Open questions
- The existing `containers/unsloth-train` (Dockerfile, requirements) still pins unsloth 2025.3.19 and transformers 4.48.3. Should the P1 D2 task adopt this spike's lock?
- Serving: should we merge (as tested), or serve base + adapter with vLLM `--enable-lora` to avoid moving 15 GB per run? This is untested, especially for NemotronH.
- Warm completion latency on the 30B was not measured.
