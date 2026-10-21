"""R10: tokens never reach artifact meta or the browser. The old vllm-serve writes {"api_key": ...} as artifact metadata,
so the API redacts secret-looking keys where meta comes in and wherever it goes out."""

from __future__ import annotations

from sqlalchemy import select

from api.models.db import AgentRun, Artifact, ArtifactKind
from api.services.redact import REDACTED, redact


def test_secret_looking_keys_are_redacted_at_any_depth():
    secrets = {"api_key", "API_KEY", "apiKey", "apikey", "x-api-key", "openai_api_key", "token", "accessToken",
               "endpoint_token", "Authorization", "client_secret", "secret_key", "password",
               "hf_token_env"}  # an _env key whose value is not an env var's name is the secret itself
    alike = {"api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "max_tokens": 512, "trained_tokens": 9, "in_tokens": 1,
             "tokenizer": "bpe", "keep_alive_min": 30, "token_count": 3,  # a ModelRef's env var name, counts, settings
             "usd_by_provider": {"token_factory": 0.12}}  # ... and Token Factory's provider name stay
    meta = {**{k: "sk-live" for k in secrets}, **alike,
            "nested": {"rows": [{"secret": {"x": 1}, "ok": 1}], "url": "https://e.example/v1"}}

    out = redact(meta)

    assert {k for k, v in out.items() if v == REDACTED} == secrets
    assert {k: out[k] for k in alike} == alike
    assert out["nested"] == {"rows": [{"secret": REDACTED, "ok": 1}], "url": "https://e.example/v1"}
    assert meta["api_key"] == "sk-live" and redact("text") == "text"  # the input stays as it was
    assert redact({"api_key_env": "sk-live-1"}) == {"api_key_env": REDACTED}


async def test_no_route_returns_an_artifact_secret(client, db, seeded_node_run):
    run, node_run = seeded_node_run
    r = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {  # old vllm-serve
        "name": "openai_api_key", "uri": "r2://orchapod-artifacts/runs/x/node/openai_api_key", "kind": "endpoint",
        "metadata": {"api_key": "sk-live-1", "model": "m"}}})
    assert r.status_code == 201
    stored = await db.scalar(select(Artifact).where(Artifact.name == "openai_api_key"))
    assert stored.meta == {"api_key": REDACTED, "model": "m"}  # never stored
    db.add(Artifact(node_run_id=node_run.id, name="legacy", kind=ArtifactKind.ENDPOINT, uri="https://e.example/v1",
                    meta={"url": "https://e.example/v1", "auth": {"token": "sk-live-2"}}))  # stored before this fix
    db.add(AgentRun(run_id=run.id, intent="i", plan={"name": "p", "nodes": []}, estimate={"usd": 0}))
    await db.commit()

    for path in (f"/runs/{run.id}/summary", f"/runs/{run.id}/artifacts", "/artifacts", f"/agent/runs/{run.id}/report"):
        r = await client.get(path)
        assert r.status_code == 200 and "sk-live" not in r.text and REDACTED in r.text, path
