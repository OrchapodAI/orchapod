"""Nebius Token Factory client (docs/contracts.md "Provider interfaces → TokenFactory").

    tf = TokenFactory(on_usage=cost.add)
    tf.chat(messages, SUPER, json_schema=schema, thinking=False)["parsed"]

Every call retries per base.request, is priced from orchapod.prices.PRICES before it is sent, reports usage
to on_usage, and never carries the Token Factory key to another URL. STUB=1 answers from a deterministic fake.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import httpx

from orchapod.prices import PRICES
from packages.providers.base import ProviderError, http_client, json_of, request, stub_hash

TF_BASE = "https://api.tokenfactory.nebius.com/v1"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
P = "token_factory"


class TokenFactory:
    """api_key defaults to NEBIUS_API_KEY; http is an httpx.Client (tests pass one on httpx.MockTransport)."""

    def __init__(self, api_key: str | None = None, *, on_usage=None, http: httpx.Client | None = None):
        self.api_key = ((os.environ.get("NEBIUS_API_KEY") if api_key is None else api_key) or "").strip()
        self.base_url = (os.environ.get("NEBIUS_BASE_URL") or TF_BASE).rstrip("/")
        self.on_usage = on_usage
        self.stub = os.environ.get("STUB") == "1"
        self.http = http_client(_stub) if self.stub or http is None else http  # STUB never touches the network
        self.files, self.fine_tuning, self.lora = _Files(self), _FineTuning(self), _Lora(self)

    def chat(self, messages: list[dict], model: str = SUPER, **kw) -> dict:
        """kw: temperature=0.0, max_tokens=1024, json_schema=None, thinking=None, read_timeout=None (seconds for this
        call; None = the client's 120 s), and for a ModelRef target base_url, api_key, base_model; anything else goes
        into the request body verbatim (top_p, stop, seed, ...). Returns {text, parsed, model, in_tokens, out_tokens,
        usd, finish_reason}."""
        url, req, bill = self._prepare(messages, model, **kw)
        data = json_of(request(self.http, P, "POST", url, **req), P)
        usage = data.get("usage") or {}
        in_tokens, out_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        usd = bill(in_tokens, out_tokens)  # first: a bad reply still cost tokens
        if not data.get("choices"):
            raise ProviderError(P, "bad_output", 200, f"{model} returned no choices")
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        parsed = None
        if kw.get("json_schema") is not None:
            try:
                parsed = json.loads(text)
            except ValueError:
                raise ProviderError(P, "bad_output", 200, f"{model} returned invalid JSON (finish_reason="
                                    f"{choice.get('finish_reason')}): raise max_tokens or set thinking=False") from None
        return {"text": text, "parsed": parsed, "model": data.get("model", model), "in_tokens": in_tokens,
                "out_tokens": out_tokens, "usd": usd, "finish_reason": choice.get("finish_reason")}

    def stream_chat(self, messages: list[dict], model: str = SUPER, **kw) -> Iterator[str]:
        """Yields content deltas (same args as chat); retries happen only before the first chunk."""
        url, req, bill = self._prepare(messages, model, stream=True, stream_options={"include_usage": True}, **kw)
        usage = {}
        resp = request(self.http, P, "POST", url, stream=True, **req)
        try:  # ponytail: a stream abandoned before its last chunk records no usage (TF sends usage last)
            for line in resp.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    if (choice.get("delta") or {}).get("content"):
                        yield choice["delta"]["content"]
        except (ValueError, AttributeError, TypeError, httpx.DecodingError) as e:  # a malformed chunk
            raise ProviderError(P, "bad_output", resp.status_code, repr(e)) from e
        except httpx.HTTPError as e:  # mid-stream: too late to retry
            raise ProviderError(P, "server", None, repr(e)) from e
        finally:
            resp.close()
        bill(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

    def _prepare(self, messages, model, *, temperature=0.0, max_tokens=1024, json_schema=None, thinking=None,
                 base_url=None, api_key=None, base_model=None, read_timeout=None, **params):
        base = (base_url or self.base_url).rstrip("/")
        key = ((api_key if base_url else self.api_key) or "").strip()  # a ModelRef brings its own key, or none
        on_tf = base == self.base_url
        if key and not on_tf and key in (self.api_key, os.environ.get("NEBIUS_API_KEY", "").strip()):
            raise ProviderError(P, "auth", None, f"refused: the Token Factory key goes only to {self.base_url}, not {base}")
        price = PRICES["token_factory"].get(model) or PRICES["token_factory"].get(base_model)
        if on_tf and not self.stub:
            if not key:
                raise ProviderError(P, "auth", None, "NEBIUS_API_KEY is not set")
            if price is None:
                raise ProviderError(P, "bad_request", None, f"no price for {model} (base_model {base_model}) in "
                                                            "orchapod.prices.PRICES; nothing is sent unpriced")
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, **params}
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": json_schema, "strict": True}}
        if thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": thinking}

        def bill(in_tokens: int, out_tokens: int) -> float:
            if not on_tf:
                return 0.0  # our own endpoints bill GPU hours, not tokens
            usd = (in_tokens * price["in"] + out_tokens * price["out"]) / 1e6 if price else 0.0
            if self.on_usage:
                self.on_usage(P, model, in_tokens, out_tokens, usd=usd)
            return usd

        timeout = httpx.Timeout(read_timeout, connect=10.0) if read_timeout else httpx.USE_CLIENT_DEFAULT
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return f"{base}/chat/completions", {"json": body, "headers": headers, "timeout": timeout}, bill

    def _call(self, method: str, path: str, *, v0: bool = False, create: bool = False, raw: bool = False, **kwargs):
        """The reply's JSON object (raw=True: the httpx.Response)."""
        if not self.api_key and not self.stub:
            raise ProviderError(P, "auth", None, "NEBIUS_API_KEY is not set")
        base = self.base_url.removesuffix("/v1") if v0 else self.base_url
        resp = request(self.http, P, method, base + path, create=create,
                       headers={"Authorization": f"Bearer {self.api_key}"}, **kwargs)
        return resp if raw else json_of(resp, P)


class _Part:
    def __init__(self, tf: TokenFactory):
        self._tf = tf


class _Files(_Part):
    def create(self, path: str | Path, purpose: str = "fine-tune") -> str:
        """Upload a file; returns its id. Sent as bytes, so a retry re-sends the whole file."""
        files = {"file": (Path(path).name, Path(path).read_bytes())}
        return self._tf._call("POST", "/files", create=True, files=files, data={"purpose": purpose})["id"]

    def get(self, file_id: str) -> dict:
        """File metadata: a checkpoint's result_files need their `filename`."""
        return self._tf._call("GET", f"/files/{file_id}")

    def content(self, file_id: str) -> bytes:
        return self._tf._call("GET", f"/files/{file_id}/content", raw=True).content


class _FineTuning(_Part):
    def create(self, model: str, training_file: str, validation_file: str | None = None,
               hyperparameters: dict | None = None, suffix: str | None = None, seed: int | None = None) -> dict:
        """Start a job; hyperparameters keep TF's names (lora, n_epochs, batch_size, learning_rate, lora_r, ...).
        Refused before sending when PRICES has no fine-tune rate for `model`."""
        if model not in PRICES["token_factory_finetune"] and not self._tf.stub:
            raise ProviderError(P, "bad_request", None, f"no fine-tune price for {model} in orchapod.prices.PRICES; "
                                                        "nothing is sent unpriced")
        body = {"model": model, "training_file": training_file, "validation_file": validation_file,
                "hyperparameters": hyperparameters, "suffix": suffix, "seed": seed}
        return self._tf._call("POST", "/fine_tuning/jobs", create=True,
                              json={k: v for k, v in body.items() if v is not None})

    def get(self, job_id: str) -> dict:
        """status ∈ validating_files | queued | running | succeeded | failed | cancelled. Poll ≥ 15 s apart."""
        return self._tf._call("GET", f"/fine_tuning/jobs/{job_id}")

    def events(self, job_id: str) -> list[dict]:
        return self._tf._call("GET", f"/fine_tuning/jobs/{job_id}/events")["data"]

    def checkpoints(self, job_id: str) -> list[dict]:
        return self._tf._call("GET", f"/fine_tuning/jobs/{job_id}/checkpoints")["data"]

    def best_checkpoint(self, job_id: str) -> dict:
        """The checkpoint with the lowest valid_loss, else the one with the highest step_number."""
        checkpoints = self.checkpoints(job_id)
        if not checkpoints:
            raise ProviderError(P, "bad_output", None, f"{job_id} has no checkpoints")
        scored = [c for c in checkpoints if (c.get("metrics") or {}).get("valid_loss") is not None]
        if scored:
            return min(scored, key=lambda c: c["metrics"]["valid_loss"])
        return max(checkpoints, key=lambda c: c["step_number"])

    def cancel(self, job_id: str) -> dict:
        return self._tf._call("POST", f"/fine_tuning/jobs/{job_id}/cancel")

    def list(self, limit: int = 20) -> list[dict]:
        """Recent jobs; find one by its `suffix` after a lost create response."""
        return self._tf._call("GET", "/fine_tuning/jobs", params={"limit": limit})["data"]


class _Lora(_Part):
    def deploy(self, name: str, base_model: str, source: str) -> str:
        """POST /v0/models with source "<job_id>:<checkpoint_id>"; returns the model id to chat with (may differ
        from `name`). Unverified until spike 1, so a missing route or a rejected base raises kind `unsupported`."""
        try:
            model = self._tf._call("POST", "/v0/models", v0=True, create=True,
                                   json={"name": name, "base_model": base_model, "source": source})
        except ProviderError as e:
            if e.status in (400, 404, 405, 422):
                raise ProviderError(P, "unsupported", e.status,
                                    f"Token Factory has no per-token LoRA deploy for {base_model} ({e.status}): "
                                    f"serve lora_adapter with vllm-serve; Token Factory said: {e.message}") from e
            raise
        return model.get("name", name)

    def status(self, name: str) -> str:
        """validating | active | error | deleted"""
        return self._tf._call("GET", f"/v0/models/{name}", v0=True)["status"]

    def delete(self, name: str) -> None:
        self._tf._call("DELETE", f"/v0/models/{name}", v0=True, raw=True)


def _minimal(schema: dict, s: str):
    """A minimal instance of a JSON schema: first enum value, s for strings, 0, false, one-item arrays."""
    if "enum" in schema:
        return schema["enum"][0]
    for alternatives in ("anyOf", "oneOf"):
        if alternatives in schema:
            return _minimal(schema[alternatives][0], s)
    kind = schema.get("type", "object")
    kind = kind[0] if isinstance(kind, list) else kind
    if kind == "object":
        return {k: _minimal(v, s) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [_minimal(schema.get("items", {}), s)]
    return {"integer": 0, "number": 0, "boolean": False, "null": None}.get(kind, s)


def _stub(request: httpx.Request) -> httpx.Response:
    """STUB=1: an offline Token Factory with the real response shapes, deterministic per request."""
    h, path = stub_hash(request), request.url.path
    body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else {}
    if path.endswith("/chat/completions"):
        schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema")
        text = f"stub-{h}" if schema is None else json.dumps(_minimal(schema, f"stub-{h}"))
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if body.get("stream"):
            chunks = [{"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}]},
                      {"choices": [], "usage": usage}]
            return httpx.Response(200, text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n")
        return httpx.Response(200, json={"model": body["model"], "usage": usage, "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]})
    if path.endswith("/content"):
        return httpx.Response(200, content=f"stub-{h}".encode())
    if path.endswith("/files"):
        return httpx.Response(200, json={"id": f"file-stub-{h}", "object": "file", "purpose": "fine-tune"})
    if "/files/" in path:
        return httpx.Response(200, json={"id": path.rsplit("/", 1)[1], "object": "file", "filename": f"stub-{h}.bin"})
    if path.endswith("/checkpoints"):
        return httpx.Response(200, json={"data": [
            {"id": f"ftckpt-stub-{h}-{step}", "step_number": step, "metrics": {"train_loss": loss, "valid_loss": loss},
             "result_files": [f"file-stub-{h}-{step}"]} for step, loss in ((1, 1.0), (2, 0.5))]})
    if path.endswith("/events"):
        return httpx.Response(200, json={"data": [{"created_at": 0, "level": "info", "message": "stub job succeeded"}]})
    if path.endswith("/fine_tuning/jobs") and request.method == "GET":
        return httpx.Response(200, json={"data": []})
    if "/fine_tuning/jobs" in path:
        rest = path.split("/fine_tuning/jobs", 1)[1].strip("/").split("/")
        return httpx.Response(200, json={
            "id": rest[0] or f"ftjob-stub-{h}", "object": "fine_tuning.job", "model": body.get("model", "stub"),
            "status": "cancelled" if rest[-1] == "cancel" else "succeeded", "error": None,
            "trained_tokens": 0, "trained_steps": 2, "total_steps": 2})
    return httpx.Response(200, json={"name": body.get("name") or path.split("/v0/models/", 1)[-1], "status": "active"})
