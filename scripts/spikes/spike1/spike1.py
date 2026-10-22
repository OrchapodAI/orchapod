"""Spike 1 (hackathon/briefs/2026-10-22-spikes.md): Token Factory models, prices, LoRA fine-tune, adapter, deploy.

    set -a; . /Users/hari/src/orchapod-hack/.env; set +a
    PYTHONPATH=.:packages/sdk-py python scripts/spikes/spike1/spike1.py <step> [args]

Steps as run on 2026-10-22: models · raw v0_models_post_empty POST /v0/models '{}' · create <model ids> ·
poll <job> · inspect <job> <dest> · deploy <job> <checkpoint> <base> · cancel_probe <train file> <val file> ·
raw delete_train_file DELETE /files/<id>. Calls go through packages.providers.tokenfactory (fetch's redirect
check is the one raw request); replies are saved under out/ as Token Factory sent them (bodies only, no headers).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from orchapod.prices import PRICES
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory

OUT = Path(__file__).parent / "out"
tf = TokenFactory()


def save(name: str, data) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def probe(name: str, method: str, path: str, **kw):
    """One call; a refusal is evidence too, so it is saved as {status, body} instead of raised."""
    try:
        data = tf._call(method, path, **kw)
    except ProviderError as e:
        data = {"status": e.status, "kind": e.kind, "body": e.message}
    save(name, data)
    return data


def models():
    """Step 0 (free): the serverless catalog with prices, Dedicated templates, the jobs list, and /v0/models."""
    listing = probe("models_verbose", "GET", "/models", params={"verbose": "true"})
    for m in listing.get("data", []):
        p = m.get("pricing") or {}
        print(f"{m['id']:<55} in {p.get('prompt')!s:<12} out {p.get('completion')!s:<12} {m.get('status')}")
    templates = probe("dedicated_templates", "GET", "/v0/dedicated_endpoints/templates", v0=True)
    print("dedicated templates:", [t.get("name") for t in templates.get("data", [])] or templates)
    print("jobs:", probe("jobs_list", "GET", "/fine_tuning/jobs", params={"limit": 5}))
    print("GET /v0/models:", probe("v0_models_get", "GET", "/v0/models", v0=True))


def rows(n: int, start: int) -> str:
    """n short chat rows in one learnable style (TF's conversational format)."""
    return "".join(json.dumps({"messages": [
        {"role": "user", "content": f"What is {a} plus {a + 7}?"},
        {"role": "assistant", "content": f"Orchapod says: {2 * a + 7}."}]}) + "\n" for a in range(start, start + n))


def create(*models: str):
    """Item 2: 50 train + 10 validation rows → files.create → fine_tuning.create (LoRA, 1 epoch) on the first
    model id TF accepts. Fine-tune prices are not public (see the report), so the spike runs on an upper bound."""
    suffix = time.strftime("spike1-%H%M", time.gmtime())
    for m in models:
        PRICES["token_factory_finetune"].setdefault(m, 10e-6)  # ponytail: spike-only $10/1M upper bound, not prices.py
    ids = {}
    for split, text in (("train", rows(50, 1)), ("val", rows(10, 101))):
        path = OUT / f"{suffix}-{split}.jsonl"
        OUT.mkdir(exist_ok=True)
        path.write_text(text)
        ids[split] = tf.files.create(path)
    print("files:", ids)
    for model in models:
        body = {"model": model, "training_file": ids["train"], "validation_file": ids["val"],
                "hyperparameters": {"lora": True, "n_epochs": 1}, "suffix": suffix}
        save(f"create_request_{model.split('/')[1]}", body)
        try:
            job = tf.fine_tuning.create(**body)
        except ProviderError as e:
            save(f"create_refused_{model.split('/')[1]}", {"status": e.status, "kind": e.kind, "body": e.message})
            print(model, "refused:", e)
            if e.kind != "bad_request":  # it may have landed: never start a second job
                raise
            continue
        save("job_created", job)
        print(json.dumps(job, indent=1))
        return


def poll(job_id: str, seconds: str = "570"):
    """Poll 20 s apart for at most `seconds` (each command stays under 600 s); every change goes to out/poll.jsonl."""
    end, last = time.time() + float(seconds), None
    while True:
        job = tf.fine_tuning.get(job_id)
        state = {k: job.get(k) for k in ("status", "trained_steps", "total_steps", "trained_tokens", "estimated_finish")}
        if state != last:
            with open(OUT / "poll.jsonl", "a") as f:
                f.write(json.dumps({"t": int(time.time()), "job": job_id, **state}) + "\n")
            print(time.strftime("%H:%M:%SZ", time.gmtime()), state, flush=True)
            last = state
        if job["status"] in ("succeeded", "failed", "cancelled") or time.time() > end:
            break
        time.sleep(20)
    save("job", job)
    save("events", tf.fine_tuning.events(job_id))


def inspect(job_id: str, dest: str):
    """Items 3-4: does the list echo suffix, newest first; raw checkpoints; the best checkpoint's files into dest."""
    jobs = tf.fine_tuning.list()
    save("jobs_list_after", jobs)
    print("list:", [(j["id"], j.get("suffix"), j.get("created_at")) for j in jobs])
    save("checkpoints", tf.fine_tuning.checkpoints(job_id))
    best = tf.fine_tuning.best_checkpoint(job_id)
    print("best:", best["id"], best["step_number"], best.get("metrics"))
    metas, folder = [], Path(dest) / best["id"]
    folder.mkdir(parents=True, exist_ok=True)
    redirects = []
    for fid in best["result_files"]:
        meta = tf.files.get(fid)
        data = fetch(fid, redirects)
        (folder / Path(meta["filename"]).name).write_bytes(data)
        metas.append(meta)
        print(f"{meta['filename']}: {meta.get('bytes')} bytes listed, {len(data)} downloaded")
    save("result_files_meta", metas)
    save("content_redirects", redirects)
    peft(folder)


def fetch(fid: str, redirects: list) -> bytes:
    """files.content; when TF answers 307 (the client refuses redirects) record where it points (host only: the
    URL is presigned) and fetch the bytes via the documented GET /files/{id}/link, without the key."""
    try:
        return tf.files.content(fid)
    except ProviderError as e:
        if e.status != 307:
            raise
    url, auth = f"{tf.base_url}/files/{fid}/content", {"Authorization": f"Bearer {tf.api_key}"}
    hop = tf.http.get(url, headers=auth)
    loc = urlsplit(hop.headers.get("location", ""))
    followed = tf.http.get(url, headers=auth, follow_redirects=True)  # httpx drops the key on a cross-origin hop
    data = httpx.get(tf._call("GET", f"/files/{fid}/link")["url"], timeout=120).content
    redirects.append({"file": fid, "status": hop.status_code, "location_host": loc.netloc, "signed_query": bool(loc.query),
                      "followed_status": followed.status_code, "followed_bytes": len(followed.content),
                      "key_sent_on_redirect": "authorization" in followed.request.headers,
                      "link_bytes": len(data), "link_equals_followed": data == followed.content})
    print(redirects[-1])
    return data


def peft(folder: Path):
    """Is it a PEFT LoRA directory? adapter_config.json fields and the safetensors header (stdlib only)."""
    cfg = json.loads((folder / "adapter_config.json").read_text())
    print({k: cfg.get(k) for k in ("peft_type", "base_model_name_or_path", "r", "lora_alpha", "target_modules",
                                   "task_type", "lora_dropout", "bias")})
    blob = (folder / "adapter_model.safetensors").read_bytes()
    header = json.loads(blob[8:8 + int.from_bytes(blob[:8], "little")])
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    print(len(tensors), "tensors;", sorted({v["dtype"] for v in tensors.values()}), "; e.g.", sorted(tensors)[:2])


def deploy(job_id: str, checkpoint_id: str, base_model: str):
    """Item 5: lora.deploy exactly as tf-deploy calls it; the refusal (or the model name) is the evidence."""
    body = {"name": time.strftime("spike1-%H%M", time.gmtime()), "base_model": base_model,
            "source": f"{job_id}:{checkpoint_id}"}
    save("deploy_request", body)
    try:
        result = {"model": tf.lora.deploy(**body)}  # active? then status, one chat and delete by hand (raw)
    except ProviderError as e:
        result = {"status": e.status, "kind": e.kind, "body": e.message}
    save("deploy_result", result)
    print(result)


def cancel_probe(training_file: str, validation_file: str, model: str = "meta-llama/Llama-3.1-8B-Instruct"):
    """R19: a second job, cancelled at once. Is the list newest-first, does it echo suffix, what does a cancel bill?"""
    PRICES["token_factory_finetune"].setdefault(model, 10e-6)  # the same spike-only upper bound as create
    job = tf.fine_tuning.create(model, training_file, validation_file, {"lora": True, "n_epochs": 1},
                                suffix=time.strftime("spike1-%H%M", time.gmtime()))
    save("cancel_probe_created", job)
    save("cancel_probe_cancel", tf.fine_tuning.cancel(job["id"]))
    jobs = tf.fine_tuning.list()
    save("cancel_probe_list", jobs)
    print("list:", [(j["id"], j.get("suffix"), j.get("created_at"), j["status"]) for j in jobs])


def raw(name: str, method: str, path: str, body: str | None = None):
    """Any one call (a POST never retries after it may have landed): raw v0_empty POST /v0/models '{}'."""
    kw = {"json": json.loads(body)} if body else {}
    data = probe(name, method, path, v0=path.startswith("/v0/"), create=method == "POST", **kw)
    print(json.dumps(data, indent=1)[:4000])


if __name__ == "__main__":
    globals()[sys.argv[1]](*sys.argv[2:])
