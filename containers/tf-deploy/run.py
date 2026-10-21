"""
containers/tf-deploy/run.py — node tf-deploy (api). Contract: docs/contracts.md "ML nodes → tf-deploy".

Deploys tf-finetune's chosen checkpoint as a per-token LoRA model (POST /v0/models), waits up to 15 min for
`active`, proves it with one 16-token completion and writes `model_ref`. A base Token Factory cannot serve per token
exits 1 pointing at vllm-serve; any later failure, timeout or cancel deletes the deployment it created. On success it
stays up: idle costs nothing, so cleanup is manual. STUB=1 runs the same path against the client's offline fake.
"""

import json
import os
import sys
import time

from orchapod import cost, io, log
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory

POLL_S, WAIT_S = 15, 15 * 60
PROMPT = [{"role": "user", "content": "In one short sentence, what can you help me with?"}]


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def read_job(value) -> dict:
    """tf-finetune's `job` output: its r2 URI, or the same JSON inline (an object or a JSON string)."""
    if isinstance(value, str):
        try:
            value = json.loads(io.download_input(value).read_text() if value.startswith("r2://") else value)
        except ValueError:
            value = None
    if not isinstance(value, dict) or not all(value.get(k) for k in ("job_id", "checkpoint_id", "model")):
        fail("job must be tf-finetune's job output (its r2 URI or the same JSON), with job_id, checkpoint_id and model")
    return value


def main():
    inputs = io.read_inputs()
    job = read_job(inputs.get("job"))
    name = inputs.get("name") or f"orchapod-{os.environ['ORCHAPOD_RUN_ID'][:8]}"
    base, source = job["model"], f"{job['job_id']}:{job['checkpoint_id']}"
    tf = TokenFactory(on_usage=cost.add)
    served, done = None, False
    try:
        try:
            served = tf.lora.deploy(name, base, source)  # the id to chat with; it may differ from `name`
        except ProviderError as e:
            if e.kind == "unsupported":
                fail(f"{e} — serve it with vllm-serve + lora_adapter")
            raise
        log.info(f"deploying {source} on {base} as {served}")
        start = time.monotonic()
        while (status := tf.lora.status(served)) != "active":
            waited = time.monotonic() - start
            if status in ("error", "deleted") or waited > WAIT_S:
                fail(f"LoRA {served} is {status} after {waited:.0f} s")
            log.progress(int(waited), WAIT_S, extra={"phase": status})
            time.sleep(POLL_S)
        wait_s = round(time.monotonic() - start)
        proof = tf.chat(PROMPT, served, max_tokens=16, base_model=base)["text"]

        ref = {"base_url": tf.base_url, "model": served, "api_key_env": "NEBIUS_API_KEY", "base_model": base}
        path = io.local_path("model_ref")
        path.write_text(json.dumps(ref))
        io.write_output("model_ref", path, kind="model", metadata={**ref, "proof": proof})
        io.write_metrics({"model": served, "base_model": base, "source": source, "wait_s": wait_s})
        done = True
        log.info(f"tf-deploy complete: {served} answered {proof!r}")
    except ProviderError as e:
        fail(str(e))
    finally:
        if served and not done:
            try:
                tf.lora.delete(served)
                log.warn(f"deleted LoRA {served}")
            except Exception as e:  # idle costs nothing, so a leftover is clutter, not spend
                log.warn(f"could not delete LoRA {served}: {e}")


if __name__ == "__main__":
    main()
