"""
containers/tf-finetune/run.py — node tf-finetune (api). Contract: docs/contracts.md "ML nodes → tf-finetune".

A retry first adopts this node's job, found by its suffix (ruling R19): a running one resumes polling, a succeeded one
goes straight to outputs. Otherwise it uploads the train (and eval) JSONL and starts a Token Factory LoRA job. It
polls every 15 s (steps → log.progress, job events → the log), keeps the checkpoint with the lowest valid_loss and
writes `job`, `lora_adapter` (PEFT dir) and metrics with the loss curve. A failure, timeout_min or cancel (SIGTERM)
cancels the job in `finally`, found by suffix if create's reply never arrived; trained tokens are billed either way.
STUB=1 runs the same path against the client's offline fake.
"""

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from orchapod import cost, io, log
from orchapod.cost import BudgetExceeded
from orchapod.prices import PRICES
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory

POLL_S = 15  # Token Factory asks for at least 15 s between polls
DONE = ("succeeded", "failed", "cancelled")


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def find(tf: TokenFactory, suffix: str) -> dict:
    """This node's live or succeeded job, by the suffix it was created with; {} if there is none."""
    jobs = tf.fine_tuning.list()
    return next((j for j in jobs if j.get("suffix") == suffix and j.get("status") not in ("failed", "cancelled")), {})


def fetch(uri: str, name: str, workdir: Path) -> Path | None:
    """An r2 JSONL input saved as <name>.jsonl, the file name Token Factory sees; None when not given or empty."""
    if not uri:
        return None
    path = io.download_input(uri, workdir).rename(workdir / f"{name}.jsonl")
    return path if path.read_bytes().strip() else None


def upload(tf: TokenFactory, inputs, model: str, hp: dict) -> tuple[str, str | None]:
    """Train (and eval) JSONL → Token Factory file ids, once the estimate fits ORCHAPOD_MAX_COST_USD."""
    workdir = Path(tempfile.mkdtemp())
    train = fetch(inputs["train_data"], "train", workdir)
    val = fetch(inputs.get("eval_data") or "", "eval", workdir)
    if train is None:
        fail(f"train_data {inputs['train_data']} is empty")
    tokens = train.stat().st_size // 4 * int(hp["n_epochs"])  # ponytail: ~4 bytes a token; tokenize if estimates miss
    est = tokens * PRICES["token_factory_finetune"].get(model, 0)  # fine_tuning.create refuses an unpriced model
    cap = os.environ.get("ORCHAPOD_MAX_COST_USD")
    if cap and est > float(cap):
        fail(f"estimated ${est:.2f} for ~{tokens} trained tokens is over ORCHAPOD_MAX_COST_USD ${float(cap):.2f}")
    return tf.files.create(train), tf.files.create(val) if val else None


def poll(tf: TokenFactory, job: dict, deadline: float) -> None:
    """Poll until the job is done: steps → log.progress, new job events → the log. Updates `job` in place, so the
    caller's `finally` sees the last status even when polling stops early."""
    seen = set()
    while job["status"] not in DONE:
        if time.monotonic() > deadline:
            fail(f"timeout: Token Factory job {job['id']} is still {job['status']} after timeout_min; cancelling it")
        time.sleep(POLL_S)
        try:
            job.update(tf.fine_tuning.get(job["id"]))
        except ProviderError as e:  # the client already retried; the job runs on, so try again at the next poll
            if e.kind not in ("server", "rate_limit"):
                raise
            log.warn(f"poll failed, next try in {POLL_S} s: {e}")
            continue
        try:  # events only inform: they never fail or cancel a job
            for event in sorted(tf.fine_tuning.events(job["id"]), key=lambda e: str(e.get("created_at"))):
                if (key := (event.get("created_at"), event.get("message"))) not in seen:
                    seen.add(key)
                    (log.info if event.get("level") == "info" else log.warn)(f"Token Factory: {event.get('message')}")
        except Exception as e:
            log.warn(f"job events unavailable: {e}")
        log.progress(job.get("trained_steps") or 0, job.get("total_steps") or 0, extra={"phase": job["status"]})


def main():
    inputs = io.read_inputs()
    start = time.monotonic()
    model = inputs.get("model") or "meta-llama/Llama-3.1-8B-Instruct"
    hp = {"lora": True, "n_epochs": int(inputs.get("n_epochs") or 2), **(inputs.get("hyperparameters") or {})}
    deadline = start + 60 * int(inputs.get("timeout_min") or 60)
    suffix = f"{os.environ['ORCHAPOD_RUN_ID'][:8]}-{os.environ['ORCHAPOD_NODE_ID']}"  # one per node of a run
    tf = TokenFactory(on_usage=cost.add)
    job, sent, paid = {}, False, False
    try:
        job = find(tf, suffix)  # R19: a retry adopts this node's job instead of paying for a second one
        if job:
            paid = job["status"] == "succeeded"  # the attempt that saw it finish billed it
            log.info(f"adopting Token Factory job {job['id']} ({job['status']}), created with suffix {suffix}")
        else:
            train_id, val_id = upload(tf, inputs, model, hp)
            sent = True  # from here a job may exist even if no reply names it
            try:
                job = tf.fine_tuning.create(model, train_id, val_id, hp, suffix=suffix)
            except ProviderError as e:  # a 5xx or read timeout may hide a job that did start
                job = find(tf, suffix) if e.kind == "server" else {}
                if not job:
                    raise
                log.warn(f"create failed ({e}), but {job['id']} carries our suffix {suffix}: continuing with it")
            if not job.get("id"):
                fail(f"Token Factory answered create without a job id: {str(job)[:200]}")
            log.info(f"Token Factory job {job['id']}: {model}, hyperparameters {hp}, validation file {val_id}")
        poll(tf, job, deadline)
        if job["status"] != "succeeded":
            fail(f"Token Factory job {job['id']} {job['status']}: {(job.get('error') or {}).get('message') or 'no message'}")

        best = tf.fine_tuning.best_checkpoint(job["id"])
        curve = [{"step": c["step_number"], "train_loss": (c.get("metrics") or {}).get("train_loss"),
                  "valid_loss": (c.get("metrics") or {}).get("valid_loss")}
                 for c in sorted(tf.fine_tuning.checkpoints(job["id"]), key=lambda c: c["step_number"])]
        adapter = io.local_path("lora_adapter")
        adapter.mkdir(parents=True, exist_ok=True)
        for file_id in best.get("result_files") or []:
            name = Path(tf.files.get(file_id).get("filename") or file_id).name  # a remote name never leaves the dir
            (adapter / name).write_bytes(tf.files.content(file_id))
        if not best.get("result_files"):
            log.warn(f"checkpoint {best['id']} has no result_files: lora_adapter is empty, so vllm-serve cannot use it")

        scores = best.get("metrics") or {}
        out = {"job_id": job["id"], "model": model, "status": job["status"], "checkpoint_id": best["id"],
               "checkpoint_step": best["step_number"], "train_loss": scores.get("train_loss"),
               "valid_loss": scores.get("valid_loss"), "trained_tokens": job.get("trained_tokens") or 0}
        path = io.local_path("job")
        path.write_text(json.dumps(out))
        io.write_output("job", path, kind="metrics", metadata=out)
        io.write_output("lora_adapter", adapter, kind="model", metadata={"format": "peft", "base_model": model})
        io.write_metrics({**out, "loss_curve": curve, "wall_s": round(time.monotonic() - start)})
        log.info(f"tf-finetune complete: checkpoint {best['id']} (step {best['step_number']}) of {job['id']}")
    except ProviderError as e:
        fail(str(e))
    finally:
        if sent and not job.get("id"):  # SIGTERM mid-POST, a bad or lost reply: a job may still have started
            try:
                job = find(tf, suffix)
            except Exception as e:
                log.error(f"could not look for the job created with suffix {suffix}, which may still bill: {e}")
        if job.get("id") and job.get("status") not in DONE:
            try:  # a reply without trained_tokens keeps the last poll's count
                job.update({k: v for k, v in tf.fine_tuning.cancel(job["id"]).items() if v is not None})
                log.warn(f"cancelled Token Factory job {job['id']}")
            except Exception as e:
                log.error(f"could not cancel Token Factory job {job['id']}, which may still bill: {e}")
        if job.get("trained_tokens") and not paid:
            with contextlib.suppress(BudgetExceeded):  # recorded before it raises; the next node boundary stops the run
                cost.add("token_factory", model, trained_tokens=job["trained_tokens"])


if __name__ == "__main__":
    main()
