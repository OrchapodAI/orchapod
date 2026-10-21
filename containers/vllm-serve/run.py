"""
containers/vllm-serve/run.py — node vllm-serve (api). Contract: docs/contracts.md "ML nodes → vllm-serve", "ModelRef",
R10, R11.

Creates a Nebius Serverless Endpoint running vLLM for `model` (a Hugging Face id, or an r2 model dir such as
unsloth-train's merged_model). With `lora_adapter` (an r2 PEFT dir, from tf-finetune or unsloth-train) it serves the base
and the adapter side by side (`--enable-lora`, the adapter as "tuned"), so judge-eval and /compare get both from one
serving stack. r2 inputs are read from our bucket, mounted read-only at /mnt/artifacts. The node waits up to 15 min for
Running, proves the served model with one completion, registers the expiry with the control plane (POST /internal/ttl
with endpoint_id; the backend deletes the endpoint then) and exits 0 with `model_ref` (and `base_model_ref`): ModelRefs
that name the env var ORCHAPOD_ENDPOINT_TOKEN, never the token. The endpoint is named per node of a run (R19), so an
endpoint an earlier attempt left is found and deleted first, and a create that may have reached Nebius without an id is
found by name and deleted. A failure or cancel before registration deletes the endpoint. STUB=1 makes no Nebius call:
the endpoint is http://stub.invalid, still registered, so /compare accepts it.
"""

import contextlib
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from orchapod import cost, io, log
from orchapod.prices import PRICES
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory

IMAGE = "vllm/vllm-openai:v0.18.0-cu130"
MOUNT = "/mnt/artifacts"
POLL_S, WAIT_S = 15, 15 * 60
MAX_LORA_RANK = 64  # vLLM's default is 16; Token Factory and unsloth-train adapters go up to 64
PROMPT = [{"role": "user", "content": "In one short sentence, what can you help me with?"}]
STUB_URL = "http://stub.invalid"


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def endpoints():
    from packages.providers.nebius import NebiusServerless  # platform's client (contracts "NebiusServerless")

    return NebiusServerless().endpoints


def mounted(name: str, uri: str, bucket: str) -> str:
    """An r2 URI in our bucket → its path on the endpoint's read-only mount."""
    if not uri.startswith(f"r2://{bucket}/"):
        fail(f"{name} must be an r2:// dir in {bucket}, the bucket the endpoint mounts, not {uri}")
    return f"{MOUNT}/{uri.removeprefix(f'r2://{bucket}/')}"


def listed(eps, name: str) -> dict | None:
    """The endpoint named `name`, from one endpoints.list() scan. A failed scan raises: find(), made for a lost create,
    would look for 45 s and call a failure a miss."""
    return next((e for e in eps.list() if e["name"] == name), None)


def clear(eps, name: str) -> None:
    """R19: names are unique per project, so an endpoint an earlier attempt of this node left is deleted (unless already
    DELETING) and the create waits until the name is free. Never adopted: get() shows no spec to check against this
    attempt's inputs."""
    old = listed(eps, name)
    if not old:
        return
    log.warn(f"endpoint {old['id']} ({name}) is {old['state']}, left by an earlier attempt: deleting it for a fresh one")
    if old["state"] != "DELETING":
        try:
            eps.delete(old["id"])
        except ProviderError as e:
            fail(f"could not delete endpoint {old['id']} ({name}): {e}; delete it in the Nebius console")
    deadline = time.monotonic() + WAIT_S
    while listed(eps, name):
        if time.monotonic() > deadline:
            fail(f"endpoint {name} is still listed {WAIT_S // 60} min after its delete; delete it in the Nebius console")
        time.sleep(POLL_S)


def running(eps, eid: str, created: float) -> str:
    """Poll until Running with a URL; another end state, or 15 min, exits 1 (the caller deletes the endpoint)."""
    while True:
        ep, waited = eps.get(eid), time.monotonic() - created
        if ep.get("state") == "RUNNING" and ep.get("url"):
            return ep["url"]
        if ep.get("state") in ("ERROR", "STOPPING", "STOPPED", "DELETING") or waited > WAIT_S:
            why = " ".join(x for x in (ep.get("code"), ep.get("message")) if x)
            fail(f"endpoint {eid} is {ep.get('state')} after {waited:.0f} s" + (f": {why}" if why else ""))
        log.progress(int(waited), WAIT_S, extra={"phase": ep.get("state")})
        time.sleep(POLL_S)


def smoke(base_url: str, served: str, token: str, created: float) -> str:
    """One short completion; while vLLM still loads behind a Running endpoint (5xx), retry until the 15-min deadline."""
    tf = TokenFactory()
    while True:
        try:
            return tf.chat(PROMPT, served, base_url=base_url, api_key=token, max_tokens=16)["text"]
        except ProviderError as e:
            if e.kind not in ("server", "rate_limit") or time.monotonic() - created > WAIT_S:
                fail(f"the endpoint did not answer: {e}")
            time.sleep(POLL_S)


def write(name: str, ref: dict, metadata: dict) -> None:
    path = io.local_path(name)
    path.write_text(json.dumps(ref))
    io.write_output(name, path, kind="model", metadata=metadata)


def main():
    inputs = io.read_inputs()
    stub = os.environ.get("STUB") == "1"
    model, adapter = str(inputs.get("model") or ""), str(inputs.get("lora_adapter") or "")
    for name, value in (("model", model), ("lora_adapter", adapter)):
        if "${{" in value:
            fail(f"unresolved ref {name}: {value}")
    if not model:
        fail("model is required: a Hugging Face id or an r2 model dir")
    keep = int(inputs.get("keep_alive_min") or 30)
    if not 1 <= keep <= 120:
        fail(f"keep_alive_min is {keep}: 1 to 120 (an L40S costs $1.55 an hour against the $3 run cap)")
    platform, preset = inputs.get("platform") or "gpu-l40s-a", inputs.get("preset") or "1gpu-8vcpu-32gb"
    price = PRICES["nebius_serverless"].get(platform)
    if price is None and not stub:
        fail(f"no price for {platform} in orchapod.prices.PRICES, so no endpoint is created")
    cap = os.environ.get("ORCHAPOD_MAX_COST_USD")
    hours = (keep + WAIT_S / 60) / 60  # billed from creation: up to WAIT_S to start, then keep_alive_min
    if cap and price and hours * price > float(cap):
        fail(f"up to {WAIT_S // 60} min to start plus {keep} min of {platform} costs up to ${hours * price:.2f}, above "
             f"this node's budget ${float(cap):.2f}")
    token = os.environ.get("ORCHAPOD_ENDPOINT_TOKEN", "").strip()
    if not stub and not token:
        fail("set ORCHAPOD_ENDPOINT_TOKEN (openssl rand -hex 32): the endpoints' bearer token")
    if not stub and not os.environ.get("ORCHAPOD_CONTROL_URL"):
        fail("ORCHAPOD_CONTROL_URL is required: the control plane deletes the endpoint at its expiry")

    bucket = os.environ.get("ORCHAPOD_R2_BUCKET") or "orchapod-artifacts"
    hf_id = None if model.startswith("r2://") else model.removeprefix("hf://")
    base_name = inputs.get("served_model_name") or hf_id or ("base" if adapter else "tuned")
    served = "tuned" if adapter else base_name
    args = [hf_id or mounted("model", model, bucket), "--served-model-name", base_name, "--port", "8000",
            "--max-model-len", str(int(inputs.get("max_model_len") or 8192)), "--dtype", inputs.get("dtype") or "bfloat16",
            "--gpu-memory-utilization", str(float(inputs.get("gpu_memory_utilization") or 0.90))]
    if adapter:
        args += ["--enable-lora", "--lora-modules", f"tuned={mounted('lora_adapter', adapter, bucket)}",
                 "--max-lora-rank", str(MAX_LORA_RANK)]
    run_id, node_id = os.environ.get("ORCHAPOD_RUN_ID", "local"), os.environ.get("ORCHAPOD_NODE_ID", "serve")
    # ponytail: node ids that differ only in case or punctuation, or share their first 45 characters, get one name, so
    # two such vllm-serve nodes in one run would delete each other's endpoint; hash the id in if canvas ids ever do that
    name = re.sub(r"[^a-z0-9-]+", "-", f"orchapod-{run_id[:8]}-{node_id}".lower())[:63].strip("-")

    eps, eid, sent, registered, created = None, None, False, False, time.monotonic()
    try:
        if stub:
            eid, url = f"stub-{name}", STUB_URL
        else:
            eps = endpoints()
            clear(eps, name)
            log.warn(f"creating endpoint {name} on {platform}/{preset}; if this node stops before it logs the endpoint "
                     f"id, delete {name} in the Nebius console")
            created, sent = time.monotonic(), True  # spend counts from here: a slow or lost create bills too
            try:
                eid = eps.create(name, IMAGE, args=" ".join(args), platform=platform, preset=preset, port=8000,
                                 env={"HF_TOKEN": os.environ["HF_TOKEN"]} if hf_id and os.environ.get("HF_TOKEN") else {},
                                 auth_token=token, volumes=(f"s3://{bucket}:{MOUNT}:ro",) if not hf_id or adapter else ())
            except ProviderError as e:  # a 409: one the scan missed holds the name; any other refusal created nothing
                sent = e.kind in ("server", "bad_output") or e.status == 409
                raise
            log.info(f"endpoint {eid} ({name}) on {platform}/{preset}: {IMAGE} {' '.join(args)}")
            url = running(eps, eid, created)
        base_url = url.rstrip("/") + "/v1"
        proof = smoke(base_url, served, token, created)
        startup_s = round(time.monotonic() - created)
        try:  # from here the backend owns the endpoint and deletes it at expiry
            log.post("/internal/ttl", {"action": "register_ttl", "keep_alive_min": keep, "endpoint_url": url,
                                       "endpoint_id": eid}, timeout=30)
        except Exception as e:
            fail(f"could not register the endpoint's expiry, so it is deleted: {e}")
        registered = True
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=keep)).isoformat()

        ref = {"base_url": base_url, "model": served, "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_model": hf_id}
        extra = {"endpoint_id": eid, "expires_at": expires_at}
        write("model_ref", ref, {**ref, **extra, "proof": proof})
        if adapter:  # the same endpoint: base and tuned share one serving stack (R11)
            base_ref = {**ref, "model": base_name, "base_model": None}
            write("base_model_ref", base_ref, {**base_ref, **extra})
        io.write_metrics({"endpoint_id": eid, "served_model": served, "platform": platform, "preset": preset,
                          "keep_alive_min": keep, "startup_s": startup_s, "expires_at": expires_at})
        log.info(f"vllm-serve complete: {served} at {base_url} answered {proof!r}; deleted at {expires_at}")
    except ProviderError as e:  # create or poll: the node's last line is the provider's
        fail(str(e))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a cancel cannot cut the lookup or the delete; docker kills at 30 s
        if sent and not eid:  # the create may have reached Nebius without returning an id (5xx, read timeout, SIGTERM),
            eid = (eps.find(name) or {}).get("id")  # or a 409 named one that holds the name
            if not eid:
                log.error(f"endpoint {name} is not listed after its create failed, but may still exist: delete it in "
                          "the Nebius console")
        if eid and not stub:
            if not registered:
                try:
                    eps.delete(eid)
                    log.warn(f"deleted endpoint {eid}")
                except Exception as e:  # it keeps billing GPU time: say so loudly
                    log.error(f"could not delete endpoint {eid}: {e}; delete it in the Nebius console")
            hours = (time.monotonic() - created) / 3600 + (keep / 60 if registered else 0)
            with contextlib.suppress(cost.BudgetExceeded):  # recorded either way; the next node boundary stops the run
                cost.add("nebius_serverless", f"{platform}/{preset}", gpu_hours=round(hours, 4))


if __name__ == "__main__":
    main()
