# Brief — spike 4: Lane B student (2026-10-20) · agent: ml-engineering
Worktree: /Users/hari/src/orchapod-hack/.claude/worktrees/ml-spike4 (branch hack/ml-spike4, base NebiusHackathon @ c866d7f). The main checkout /Users/hari/src/orchapod-hack is read-only for you. Do not dispatch subagents.

## Goal
Decide the Lane B student: can we LoRA-train, merge and serve a Nemotron student with Unsloth + vLLM on one 80 GB GPU? Nebius GPU quota is pending, so this runs on a rented vast.ai GPU. It produces numbers for a decision, never a claim about Nebius.

## Steps
1. Secrets: `set -a; . /Users/hari/src/orchapod-hack/.env; set +a` (VASTAI_API_KEY, HF_TOKEN); never print them. Use the `vastai` CLI from /Users/hari/src/orchapod-hack/.venv. Confirm `vastai show instances` is empty first.
2. Rent ONE instance: 1× A100 80 GB (an H100 80 GB is fine if cheaper per hour), reliability ≥ 0.98, ≥ 120 GB disk, ≤ $1.60/h, an image with CUDA 12.x and PyTorch. Install a shell trap that runs `vastai destroy instance <id>` on exit.
3. Access: SSH with an already-attached account key if one matches ~/.ssh; otherwise create a throwaway ed25519 key under $TMPDIR/orchapod-spike4/ and attach it to this instance only (`vastai attach ssh`). Never change account-level settings. Send no secrets to the host; if a model needs HF_TOKEN, stop and report instead.
4. Main run: Unsloth 16-bit LoRA (load_in_4bit=False) on nvidia/Llama-3.1-Nemotron-Nano-8B-v1 with 200 rows of a public instruction dataset (e.g. yahma/alpaca-cleaned), about 60 steps. Record the loss over the first and last 5 steps, merge to 16-bit, serve the merged model with vLLM, and get one chat completion. Record wall time per phase.
5. Stretch, only if both caps still allow it: the same on Nemotron 3 Nano 30B-A3B (verify the exact HF id; keep the router frozen). Keep it only if merge and serve both work.
6. Destroy the instance and confirm `vastai show instances` is empty.

## Limits
At most $6 in total and 3 h from instance creation (hard stop: destroy and report). Any remote step silent for more than 20 min: destroy and report. Foreground commands only, each with a timeout of at most 600 s; poll long remote work in chunks of at most 600 s.

## Deliverables
- Commits on hack/ml-spike4: containers/unsloth-train/spike/ (the scripts you ran, with pinned versions) and containers/unsloth-train/spike/RESULTS.md (instance type, $/h, total $, wall times, losses, merge and serve outcome, completion text, surprises).
- Full report: /Users/hari/src/orchapod-hack/hackathon/briefs/2026-10-20-ml-engineering-spike4-report.md.
- Final message at most 10 lines: branch and SHAs, losses first → last, the served completion (one line), total $ and wall time, `vastai show instances` output, recommended student (DECISION).
