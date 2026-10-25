"""R10: tokens never reach artifact meta or the browser. The old vllm-serve writes {"api_key": ...} as artifact metadata,
so the API redacts secret-looking keys where meta comes in and wherever it goes out."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.models.db import AgentRun, Artifact, ArtifactKind
from api.services.redact import REDACTED, redact, redact_text
from tests.api.test_executor import nebius  # noqa: F401 (fixture)


SECRETS = {"api_key", "API_KEY", "apiKey", "apikey", "x-api-key", "openai_api_key", "token", "accessToken",
           "endpoint_token", "Authorization", "client_secret", "secret_key", "password",
           "hf_token_env",  # an _env key whose value is not an env var's name is the secret itself
           "HFToken", "APIToken", "APIKey", "OAuthToken",  # acronyms in camelCase
           "access_key", "accessKey", "aws_access_key_id", "AWSAccessKeyId"}
ALIKE = {"api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "max_tokens": 512, "trained_tokens": 9, "in_tokens": 1,
         "tokenizer": "bpe", "keep_alive_min": 30, "token_count": 3,  # a ModelRef's env var name, counts, settings
         "usd_by_provider": {"token_factory": 0.12},  # ... and Token Factory's provider name stay
         "maxTokens": 9, "GPUHours": 0.5, "HFModel": "m", "TokenFactory": "tf"}  # acronyms that are no secret


def test_secret_looking_keys_are_redacted_at_any_depth():
    meta = {**{k: "sk-live" for k in SECRETS}, **ALIKE,
            "nested": {"rows": [{"secret": {"x": 1}, "ok": 1}], "url": "https://e.example/v1"}}

    out = redact(meta)

    assert {k for k, v in out.items() if v == REDACTED} == SECRETS
    assert {k: out[k] for k in ALIKE} == ALIKE
    assert out["nested"] == {"rows": [{"secret": REDACTED, "ok": 1}], "url": "https://e.example/v1"}
    assert meta["api_key"] == "sk-live" and redact("text") == "text"  # the input stays as it was
    assert redact({"api_key_env": "sk-live-1"}) == {"api_key_env": REDACTED}


def test_redact_text_applies_the_same_key_rule_to_pairs_in_free_text():
    """A log line is free text: its key=value, key: value and "key": "value" pairs go by redact()'s rule, key by key."""
    plain = {k: v for k, v in ALIKE.items() if not isinstance(v, dict)}
    shapes = (lambda k, v: f"go {k}={v} on", lambda k, v: f"go {k}: {v} on", lambda k, v: f'go {{"{k}": "{v}"}} on')
    for shape in shapes:
        for k in SECRETS:
            assert redact_text(shape(k, "sk-live")) == shape(k, REDACTED), k
        for k, v in plain.items():
            assert redact_text(shape(k, v)) == shape(k, v), k
    assert redact_text("Authorization: Bearer abc.def-1 ok") == f"Authorization: {REDACTED} ok"
    assert redact_text("GET /v1?model=m&token=abc&x=1") == f"GET /v1?model=m&token={REDACTED}&x=1"
    assert redact_text(redact_text("api_key=a")) == f"api_key={REDACTED}"  # again changes nothing
    assert redact_text("no secrets: just words, 1:2 and a=b") == "no secrets: just words, 1:2 and a=b"


SHAPES = [  # a secret inside a value that is none, a bare token, the password of a URL: what a pair-by-pair scan misses
    ("ValueError: api_key=AAA111 is invalid", f"ValueError: api_key={REDACTED} is invalid"),
    ("Error: NEBIUS_API_KEY=sk-live-123", f"Error: NEBIUS_API_KEY={REDACTED}"),
    ("url=https://h/p?token=t0k&x=1", f"url=https://h/p?token={REDACTED}&x=1"),
    ("GET https://h/x?token=t0k&y=1", f"GET https://h/x?token={REDACTED}&y=1"),
    ("auth 401: token: v1.CmSECRET", f"auth 401: token: {REDACTED}"),
    ("DATABASE_URL=postgresql://u:pw@db/o", f"DATABASE_URL=postgresql://{REDACTED}@db/o"),
    ("sent Bearer eyJhbGciOiJIUzI1NiJ9.sig now", f"sent Bearer {REDACTED} now"),
    ("header: Basic dXNlcjpwYXNzd29yZA== sent", f"header: Basic {REDACTED} sent"),
    ("clone https://user:pw@host/repo.git", f"clone https://{REDACTED}@host/repo.git"),
    ("redis://:pw@cache:6379/0", f"redis://{REDACTED}@cache:6379/0"),
    ('{"error": "ValueError: api_key=AAA111", "url": "https://h?token=T0K"}',
     f'{{"error": "ValueError: api_key={REDACTED}", "url": "https://h?token={REDACTED}"}}'),
    ("a=1 api_key=k1 and b: token: t2 then Bearer abcdefgh3", f"a=1 api_key={REDACTED} and b: token: {REDACTED} then Bearer {REDACTED}"),
]


@pytest.mark.parametrize("text, redacted", SHAPES)
def test_redact_text_finds_a_secret_in_a_value_a_bare_token_and_a_urls_password(text, redacted):
    assert redact_text(text) == redacted
    assert redact_text(redacted) == redacted  # again changes nothing


def test_redact_text_leaves_prose_and_short_words_alone_and_never_recurses():
    for text in ("no secrets: just words, 1:2 and a=b", "Basic usage of Bearer tokens: see https://docs.nebius.com/x?page=2",
                 "mailto://a@b.c and ssh://git@github.com/org", "key=value; token_count=5 max_tokens: 512"):
        assert redact_text(text) == text, text
    pairs = "a:" * 1000  # the 2,000 characters of a line, a pair in every value: a recursive scan raised RecursionError
    assert redact_text(pairs) == pairs
    assert redact_text(pairs + "api_key=zzz") == pairs + f"api_key={REDACTED}"
    assert redact_text("x" * 5000 + " " * 5000 + "y=" * 1000) == "x" * 5000 + " " * 5000 + "y=" * 1000  # long words and gaps


@pytest.mark.usefixtures("nebius")  # the summary looks a running vllm-serve up at Nebius: faked
async def test_no_route_returns_an_artifact_secret(client, db, seeded_node_run):
    run, node_run = seeded_node_run
    r = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {  # old vllm-serve
        "name": "openai_api_key", "uri": "r2://orchapod-artifacts/runs/x/node/openai_api_key", "kind": "metrics",
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


def test_without_secrets_drops_secret_keys_at_any_depth_of_an_input():
    from api.services.redact import without_secrets
    inputs = {"cfg": {"hf_token": "hf_X", "HFToken": "hf_Y", "accessKey": "AK", "k": 1}, "refs": [{"api_key": "sk-X", "model": "m"}],
              "headers": {"Authorization": "Bearer X"}, "max_tokens": 5, "api_key_env": "NEBIUS_API_KEY"}
    out = without_secrets({"nodes": [{"id": "n", "inputs": inputs}]})["nodes"][0]["inputs"]
    assert out == {"cfg": {"k": 1}, "refs": [{"model": "m"}], "headers": {}, "max_tokens": 5, "api_key_env": "NEBIUS_API_KEY"}
