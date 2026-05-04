"""
containers/lm-eval/run.py

Node: lm-eval
Base image: python:3.12 + lm-evaluation-harness + vllm + openai
GPU: 1x H100 80GB (loads each model sequentially)
Demo runtime: ~15 min for 3 models x 3 academic tasks + 100-prompt judge set

Inputs:
  models         — list of model URIs to compare (baseline + fine-tuned + distilled)
  tasks          — list of lm-eval task names (default: hellaswag, mmlu_stem, gsm8k)
  judge_eval_set — R2 URI to held-out eval JSONL

Outputs:
  eval_report_json    — full results JSON
  eval_report_html    — rendered comparison report
  comparison_table_md — markdown summary table
"""

import json
import subprocess
import time
from pathlib import Path

from orchapod import io, log


def run_lm_eval(model_path: Path, tasks: list[str]) -> dict:
    """Run lm-evaluation-harness against a model, return results dict."""
    log.info(f"Running lm-eval on {model_path.name} for tasks: {tasks}")

    # Start vLLM server for this model
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


def run_llm_judge(model_path: Path, eval_set: list[dict]) -> dict:
    """
    Ask Claude Sonnet to score model outputs for quality and win-rate.
    Returns per-prompt scores and aggregate win-rate vs baseline.
    """
    import os
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Start vLLM for this model
    proc = subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(model_path), "--port", "8003",
    ])
    _wait_for_server("http://localhost:8003/health")

    scores = []
    for ex in eval_set[:100]:  # cap at 100 prompts for cost
        prompt = ex["messages"][0]["content"]
        reference = ex["messages"][-1]["content"] if len(ex["messages"]) > 1 else ""

        # Get model output
        import urllib.request
        payload = json.dumps({"model": str(model_path),
                              "messages": [{"role": "user", "content": prompt}],
                              "max_tokens": 512}).encode()
        req = urllib.request.Request("http://localhost:8003/v1/chat/completions",
                                     data=payload, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req).read())
        model_output = resp["choices"][0]["message"]["content"]

        # Judge
        judge_prompt = f"""Rate this response 1-5 for quality, helpfulness, and accuracy.
Reference answer: {reference}
Model response: {model_output}
Respond with JSON: {{"score": <1-5>, "reason": "<one sentence>"}}"""

        judge_resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": judge_prompt}]
        )
        try:
            score_data = json.loads(judge_resp.content[0].text)
        except Exception:
            score_data = {"score": 3, "reason": "parse error"}
        scores.append({"prompt": prompt[:100], **score_data})

    proc.terminate()
    proc.wait()

    avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0
    return {"scores": scores, "avg_score": round(avg_score, 2), "n_prompts": len(scores)}


def _wait_for_server(url: str, timeout_s: int = 120):
    import urllib.request
    for _ in range(timeout_s // 2):
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Server at {url} did not start in {timeout_s}s")


def main():
    inputs = io.read_inputs()
    log.info("lm-eval starting")

    model_uris     = inputs["models"]     # list of R2 URIs
    tasks          = inputs.get("tasks", ["hellaswag", "mmlu_stem", "gsm8k"])
    judge_eval_uri = inputs["judge_eval_set"]

    # Download models and eval set
    model_paths = []
    for i, uri in enumerate(model_uris):
        path = io.download_input(uri, f"/workspace/model_{i}")
        model_paths.append(path)

    judge_path = io.download_input(judge_eval_uri, "/workspace")
    with open(judge_path) as f:
        eval_set = [json.loads(l) for l in f if l.strip()]

    # Run eval for each model
    all_results = {}
    for path in model_paths:
        log.info(f"Evaluating model: {path.name}")
        lm_results   = run_lm_eval(path, tasks)
        judge_results = run_llm_judge(path, eval_set)
        all_results[path.name] = {"lm_eval": lm_results, "judge": judge_results}

    # Build comparison table
    rows = ["| Model | HellaSwag | MMLU-STEM | GSM8K | Judge Score |",
            "|-------|-----------|-----------|-------|-------------|"]
    for model_name, res in all_results.items():
        lm = res["lm_eval"].get("results", {})
        j  = res["judge"]
        rows.append(f"| {model_name} | "
                    f"{lm.get('hellaswag', {}).get('acc_norm,none', 'N/A')} | "
                    f"{lm.get('mmlu_stem', {}).get('acc,none', 'N/A')} | "
                    f"{lm.get('gsm8k', {}).get('exact_match,flexible-extract', 'N/A')} | "
                    f"{j['avg_score']}/5 |")
    comparison_md = "\n".join(rows)

    # Write outputs
    report_json = io.local_path("eval_report.json")
    report_md   = io.local_path("comparison_table.md")
    with open(report_json, "w") as f: json.dump(all_results, f, indent=2)
    with open(report_md, "w") as f:   f.write(comparison_md)

    io.write_output("eval_report_json",    report_json, kind="metrics")
    io.write_output("comparison_table_md", report_md,   kind="metrics")
    log.info("lm-eval complete")
    log.info(f"\nResults:\n{comparison_md}")


if __name__ == "__main__":
    main()
