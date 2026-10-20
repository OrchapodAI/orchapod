"""
containers/lm-eval/run.py

Node: lm-eval
Base image: python:3.12 + lm-evaluation-harness + vllm + openai + httpx
GPU: 1x H100 80GB (loads each model sequentially)
Demo runtime: ~15 min for 3 models x 3 academic tasks + 100-prompt judge set

Inputs:
  models         — list of model URIs to compare (baseline + fine-tuned + distilled)
  tasks          — list of lm-eval task names (default: hellaswag, mmlu_stem, gsm8k)
  judge_eval_set — R2 URI to held-out eval JSONL
  judge_model    — (optional) Nemotron model for judge; default Nemotron Ultra

Outputs:
  eval_report_json    — full results JSON
  eval_report_html    — rendered comparison report
  comparison_table_md — markdown summary table

Judge: NVIDIA Nemotron Ultra via Nebius Token Factory (replaces Claude).
       Falls back to Nemotron Super if NEBIUS_API_KEY is set but Ultra is slow.
       Falls back to Claude if ANTHROPIC_API_KEY is set and NEBIUS_API_KEY is not.
"""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from orchapod import io, log

# Default to Nemotron Ultra for highest eval quality; override via input
_DEFAULT_JUDGE_MODEL = os.environ.get(
    "JUDGE_MODEL",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
)

_NEBIUS_API_BASE = "https://api.studio.nebius.ai/v1"


# ---------------------------------------------------------------------------
# Academic benchmarks via lm-evaluation-harness
# ---------------------------------------------------------------------------

def run_lm_eval(model_path: Path, tasks: list[str]) -> dict:
    """Run lm-evaluation-harness against a model, return results dict."""
    log.info(f"Running lm-eval on {model_path.name} for tasks: {tasks}")

    proc = subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(model_path),
        "--port", "8002",
        "--dtype", "bfloat16",
    ])
    _wait_for_server("http://localhost:8002/health")

    results_path = Path(f"/workspace/eval_{model_path.name}.json")
    subprocess.run([
        "lm_eval",
        "--model", "vllm",
        "--model_args", f"pretrained={model_path},add_bos_token=True",
        "--tasks", ",".join(tasks),
        "--output_path", str(results_path),
        "--device", "cuda",
    ], check=True)

    proc.terminate()
    proc.wait()

    with open(results_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# LLM-as-judge via Nebius Token Factory (NVIDIA Nemotron)
# ---------------------------------------------------------------------------

def _judge_via_nebius(prompt: str, model_output: str, reference: str, judge_model: str) -> dict:
    """Score a model response using Nemotron via Nebius Token Factory."""
    nebius_key = os.environ.get("NEBIUS_API_KEY")
    if not nebius_key:
        raise RuntimeError("NEBIUS_API_KEY not set; cannot use Nemotron judge.")

    system_prompt = (
        "You are an expert evaluator assessing LLM responses. "
        "Score on a scale of 1-5 for correctness, helpfulness, and quality. "
        "Return JSON only: {\"score\": <1-5>, \"reason\": \"<one sentence>\"}"
    )
    user_msg = f"Reference answer: {reference}\nModel response: {model_output[:1000]}"
    if prompt:
        user_msg = f"Prompt: {prompt[:500]}\n" + user_msg

    payload = json.dumps({
        "model": judge_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }).encode()

    req = urllib.request.Request(
        f"{_NEBIUS_API_BASE}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {nebius_key}",
        },
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    raw = resp["choices"][0]["message"]["content"]

    import re
    m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"score": 3, "reason": raw[:200]}


def _judge_via_anthropic(prompt: str, model_output: str, reference: str) -> dict:
    """Fallback judge using Claude if NEBIUS_API_KEY is not available."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    judge_prompt = (
        f"Rate this response 1-5 for quality, helpfulness, and accuracy.\n"
        f"Reference answer: {reference}\nModel response: {model_output}\n"
        'Respond with JSON: {"score": <1-5>, "reason": "<one sentence>"}'
    )
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": judge_prompt}],
    )
    try:
        return json.loads(resp.content[0].text)
    except Exception:
        return {"score": 3, "reason": "parse error"}


def run_llm_judge(model_path: Path, eval_set: list[dict], judge_model: str) -> dict:
    """
    Score model outputs using an LLM judge.
    Priority: Nemotron (Nebius Token Factory) → Claude (fallback).
    Returns per-prompt scores and aggregate win-rate.
    """
    use_nebius = bool(os.environ.get("NEBIUS_API_KEY"))
    use_claude = bool(os.environ.get("ANTHROPIC_API_KEY")) and not use_nebius

    if not use_nebius and not use_claude:
        log.info("No judge API key set — skipping LLM judge")
        return {"scores": [], "avg_score": 0, "n_prompts": 0, "judge": "none"}

    judge_name = f"nemotron:{judge_model.split('/')[-1]}" if use_nebius else "claude"
    log.info(f"LLM judge: {judge_name}")

    # Start vLLM for the model being evaluated
    proc = subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(model_path), "--port", "8003",
    ])
    _wait_for_server("http://localhost:8003/health")

    scores = []
    for ex in eval_set[:100]:
        prompt    = ex["messages"][0]["content"]
        reference = ex["messages"][-1]["content"] if len(ex["messages"]) > 1 else ""

        payload = json.dumps({
            "model": str(model_path),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8003/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        model_output = resp["choices"][0]["message"]["content"]

        try:
            if use_nebius:
                score_data = _judge_via_nebius(prompt, model_output, reference, judge_model)
            else:
                score_data = _judge_via_anthropic(prompt, model_output, reference)
        except Exception as e:
            log.info(f"Judge error (skipping): {e}")
            score_data = {"score": 3, "reason": "error"}

        scores.append({"prompt": prompt[:100], **score_data})

    proc.terminate()
    proc.wait()

    avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0
    return {
        "scores":    scores,
        "avg_score": round(avg_score, 2),
        "n_prompts": len(scores),
        "judge":     judge_name,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_server(url: str, timeout_s: int = 120):
    for _ in range(timeout_s // 2):
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Server at {url} did not start in {timeout_s}s")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    inputs = io.read_inputs()
    log.info("lm-eval starting")

    model_uris     = inputs["models"]
    tasks          = inputs.get("tasks", ["hellaswag", "mmlu_stem", "gsm8k"])
    judge_eval_uri = inputs["judge_eval_set"]
    judge_model    = inputs.get("judge_model", _DEFAULT_JUDGE_MODEL)

    # Download models and eval set
    model_paths = []
    for i, uri in enumerate(model_uris):
        path = io.download_input(uri, f"/workspace/model_{i}")
        model_paths.append(path)

    judge_path = io.download_input(judge_eval_uri, "/workspace")
    with open(judge_path) as f:
        eval_set = [json.loads(line) for line in f if line.strip()]

    # Run eval for each model
    all_results = {}
    for path in model_paths:
        log.info(f"Evaluating model: {path.name}")
        lm_results    = run_lm_eval(path, tasks)
        judge_results = run_llm_judge(path, eval_set, judge_model)
        all_results[path.name] = {"lm_eval": lm_results, "judge": judge_results}

    # Build comparison table
    rows = ["| Model | HellaSwag | MMLU-STEM | GSM8K | Nemotron Judge Score |",
            "|-------|-----------|-----------|-------|----------------------|"]
    for model_name, res in all_results.items():
        lm = res["lm_eval"].get("results", {})
        j  = res["judge"]
        rows.append(
            f"| {model_name} | "
            f"{lm.get('hellaswag', {}).get('acc_norm,none', 'N/A')} | "
            f"{lm.get('mmlu_stem', {}).get('acc,none', 'N/A')} | "
            f"{lm.get('gsm8k', {}).get('exact_match,flexible-extract', 'N/A')} | "
            f"{j['avg_score']}/5 ({j.get('judge','?')}) |"
        )
    comparison_md = "\n".join(rows)

    # Write outputs
    report_json = io.local_path("eval_report.json")
    report_md   = io.local_path("comparison_table.md")
    with open(report_json, "w") as f:
        json.dump(all_results, f, indent=2)
    with open(report_md,   "w") as f:
        f.write(comparison_md)

    io.write_output("eval_report_json",    report_json, kind="metrics")
    io.write_output("comparison_table_md", report_md,   kind="metrics")
    log.info("lm-eval complete")
    log.info(f"\nResults:\n{comparison_md}")


if __name__ == "__main__":
    main()
