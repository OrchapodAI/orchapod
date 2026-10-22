"""TokenFactory client against recorded Token Factory responses (OpenAI-compatible shapes; no live calls)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from orchapod.prices import PRICES
from packages.providers import tokenfactory
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import SUPER, TokenFactory

SPIKE1 = Path(__file__).resolve().parents[2] / "scripts" / "spikes" / "spike1" / "out"  # live replies, 2026-10-22


def recorded(name: str):
    return json.loads((SPIKE1 / f"{name}.json").read_text())


MSGS = [{"role": "user", "content": "hi"}]
LLAMA = "meta-llama/Llama-3.1-8B-Instruct"  # unpriced until spike 1
SCORE = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}


def completion(content="Hello.", finish_reason="stop", model=SUPER):
    return httpx.Response(200, json={
        "id": "chatcmpl-0a1b", "object": "chat.completion", "created": 1760990000, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
    })


SUPER_USD = 1000 * 0.30 / 1e6 + 2000 * 0.90 / 1e6
JOB = {"id": "ftjob-7f3a", "object": "fine_tuning.job", "model": LLAMA, "status": "validating_files",
       "training_file": "file-1", "validation_file": None, "trained_tokens": None, "error": None}


@pytest.fixture
def ft_priced(monkeypatch):
    monkeypatch.setitem(PRICES["token_factory_finetune"], LLAMA, 1e-6)


@pytest.fixture
def train(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text('{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}\n')
    return path


CREATES = {  # every paid create call site, and the reply that means "created"
    "files.create": (lambda tf, train: tf.files.create(train), {"id": "file-1"}),
    "fine_tuning.create": (lambda tf, train: tf.fine_tuning.create(LLAMA, "file-1"), JOB),
    "lora.deploy": (lambda tf, train: tf.lora.deploy("orchapod-1234abcd", LLAMA, "ftjob-7f3a:ftckpt-2"),
                    {"name": "orchapod-1234abcd", "status": "validating"}),
}


# --- retries --------------------------------------------------------------

def test_429_waits_retry_after_capped_at_60s(replay, sleeps):
    http, seen = replay(httpx.Response(429, headers={"Retry-After": "7"}),
                        httpx.Response(429, headers={"Retry-After": "300"}), completion())
    assert TokenFactory(http=http).chat(MSGS)["text"] == "Hello."
    assert len(seen) == 3 and sleeps == [7, 60]


def test_5xx_retried_three_times_with_backoff_then_server_error(replay, sleeps):
    http, seen = replay(*[httpx.Response(503, text="overloaded") for _ in range(4)])
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS)
    assert (e.value.kind, e.value.status, len(seen)) == ("server", 503, 4)
    assert [int(s) for s in sleeps] == [1, 2, 4]  # plus < 1 s jitter each


@pytest.mark.parametrize("first", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
def test_timeouts_and_connection_errors_retried(replay, first):
    http, seen = replay(first, completion())
    assert TokenFactory(http=http).chat(MSGS)["text"] == "Hello." and len(seen) == 2


@pytest.mark.parametrize("site", CREATES)
@pytest.mark.parametrize("first", [lambda: httpx.Response(500, text="boom"), lambda: httpx.ReadTimeout("slow"),
                                   lambda: httpx.RemoteProtocolError("dropped")], ids=["5xx", "read_timeout", "dropped"])
def test_create_never_retried_once_the_request_may_have_landed(replay, ft_priced, train, site, first):
    call, _ = CREATES[site]
    http, seen = replay(first())
    with pytest.raises(ProviderError) as e:
        call(TokenFactory(http=http), train)
    assert e.value.kind == "server" and len(seen) == 1


@pytest.mark.parametrize("site", CREATES)
def test_create_retried_on_429_and_connect_errors(replay, ft_priced, train, site):
    call, created = CREATES[site]
    http, seen = replay(httpx.Response(429), httpx.ConnectError("refused"), httpx.ConnectTimeout("slow connect"),
                        httpx.Response(200, json=created))
    call(TokenFactory(http=http), train)
    assert len(seen) == 4


def test_any_transport_error_is_retried_then_a_provider_error(replay):
    http, seen = replay(*[httpx.ProxyError("proxy down") for _ in range(4)])
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS)
    assert (e.value.kind, len(seen)) == ("server", 4)


def test_redirect_is_not_success(replay):
    http, seen = replay(httpx.Response(307, headers={"location": "https://elsewhere.example/v1/chat/completions"}))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS)
    assert (e.value.kind, e.value.status, len(seen)) == ("bad_request", 307, 1)


@pytest.mark.parametrize("status,kind", [(400, "bad_request"), (404, "bad_request"), (409, "bad_request"),
                                         (422, "bad_request"), (401, "auth"), (403, "auth"), (402, "quota")])
def test_client_errors_not_retried(replay, status, kind):
    http, seen = replay(httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS)
    assert (e.value.kind, e.value.status, len(seen)) == (kind, status, 1)
    assert str(e.value).startswith(f"token_factory {kind} {status}: ") and "nope" in str(e.value)


# --- key and price guards -------------------------------------------------

def test_token_factory_key_never_sent_off_token_factory(replay):
    http, seen = replay(completion(model="tuned"), completion(model="tuned"))
    tf = TokenFactory(http=http)
    with pytest.raises(ProviderError) as e:
        tf.chat(MSGS, "tuned", base_url="https://evil.example/v1", api_key="tf-key")
    assert e.value.kind == "auth" and seen == []
    for kw in ({}, {"api_key": ""}):  # no key (unset api_key_env; judge-eval's llama-server): sent with none
        tf.chat(MSGS, "tuned", base_url="http://127.0.0.1:8080/v1", **kw)
    assert [r.headers.get("authorization") for r in seen] == [None, None]


@pytest.mark.parametrize("call", ["chat", "stream_chat"])
@pytest.mark.parametrize("client_key,env_key,ref_key", [  # client_key None = NEBIUS_API_KEY
    (None, "tf-key", "tf-key"), (None, "tf-key", " tf-key\n"), ("own-key", "tf-key\n", "tf-key"), (" tf-key\n", "", "tf-key")])
def test_token_factory_key_refused_off_token_factory_even_padded(replay, monkeypatch, call, client_key, env_key, ref_key):
    monkeypatch.setenv("NEBIUS_API_KEY", env_key)
    http, seen = replay(completion(model="tuned"))
    tf = TokenFactory(client_key, http=http)
    with pytest.raises(ProviderError) as e:  # list() drains stream_chat's generator; chat raises before it returns
        list(getattr(tf, call)(MSGS, "tuned", base_url="https://evil.example/v1", api_key=ref_key))
    assert e.value.kind == "auth" and seen == []


def test_endpoint_model_ref_is_sent_with_its_own_key_and_unbilled(replay, recorder):
    calls, on_usage = recorder
    http, seen = replay(completion(model="tuned"))
    out = TokenFactory(on_usage=on_usage, http=http).chat(
        MSGS, "tuned", base_url="https://ep.example/v1", api_key="ep-token", base_model=LLAMA)
    assert str(seen[0].url) == "https://ep.example/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer ep-token"
    assert out["usd"] == 0 and calls == []


def test_unpriced_model_fails_before_send(replay):
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS, LLAMA)
    assert e.value.kind == "bad_request" and seen == []


def test_unpriced_fine_tune_fails_before_send(replay):
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).fine_tuning.create(LLAMA, "file-1")
    assert e.value.kind == "bad_request" and seen == []


def test_lora_is_priced_by_its_base_model(replay):
    http, _ = replay(completion(model="my-lora"))
    assert TokenFactory(http=http).chat(MSGS, "my-lora", base_model=SUPER)["usd"] == pytest.approx(SUPER_USD)


def test_missing_key_is_auth_error_before_send(replay, monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY")
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).chat(MSGS)
    assert e.value.kind == "auth" and seen == []


# --- chat -----------------------------------------------------------------

def test_json_schema_is_parsed_and_billed(replay, monkeypatch, recorder):
    monkeypatch.setenv("NEBIUS_BASE_URL", "")  # blank = the default
    calls, on_usage = recorder
    http, seen = replay(completion('{"score": 4}'))
    out = TokenFactory(on_usage=on_usage, http=http).chat(MSGS, json_schema=SCORE, thinking=False, seed=7)
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.tokenfactory.nebius.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer tf-key"
    assert body["response_format"] == {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": SCORE, "strict": True}}
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["seed"] == 7
    assert out == {"text": '{"score": 4}', "parsed": {"score": 4}, "model": SUPER, "in_tokens": 1000,
                   "out_tokens": 2000, "usd": pytest.approx(SUPER_USD), "finish_reason": "stop"}
    assert calls == [(("token_factory", SUPER, 1000, 2000), {"usd": pytest.approx(SUPER_USD)})]


def test_invalid_json_is_bad_output_billed_and_not_retried(replay, recorder):
    calls, on_usage = recorder
    http, seen = replay(completion('{"score": ', finish_reason="length"))
    with pytest.raises(ProviderError) as e:
        TokenFactory(on_usage=on_usage, http=http).chat(MSGS, json_schema=SCORE)
    assert e.value.kind == "bad_output" and "length" in str(e.value)
    assert len(seen) == 1 and len(calls) == 1  # the tokens were spent


def test_read_timeout_is_per_call_and_not_in_the_body(replay):
    http, seen = replay(completion(), completion())
    tf = TokenFactory(http=http)
    tf.chat(MSGS, read_timeout=300)
    tf.chat(MSGS)
    assert [r.extensions["timeout"] for r in seen] == [{"connect": 10, "read": 300, "write": 120, "pool": 120},
                                                       {"connect": 5, "read": 5, "write": 5, "pool": 5}]
    assert "read_timeout" not in json.loads(seen[0].content)  # the second: this test client's own default


def undecodable():  # a gzip body that is not gzip, read only when the client reads it
    return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"\x00garbage"))


@pytest.mark.parametrize("reply", [lambda: httpx.Response(200, text="<html>gateway</html>"),
                                   lambda: httpx.Response(200, json=["not", "an", "object"]), undecodable],
                         ids=["not_json", "not_an_object", "undecodable"])
@pytest.mark.parametrize("call", [lambda tf: tf.chat(MSGS), lambda tf: tf.fine_tuning.get("ftjob-7f3a")],
                         ids=["chat", "fine_tuning.get"])
def test_a_2xx_reply_that_cannot_be_read_is_bad_output_not_retried(replay, reply, call):
    http, seen = replay(reply())
    with pytest.raises(ProviderError) as e:
        call(TokenFactory(http=http))
    assert (e.value.kind, len(seen)) == ("bad_output", 1)


@pytest.mark.parametrize("reply", [lambda: httpx.Response(200, text="data: {not json\n\n"),
                                   lambda: httpx.Response(200, text='data: "a string"\n\n'), undecodable],
                         ids=["not_json", "not_an_object", "undecodable"])
def test_malformed_stream_chunk_is_bad_output(replay, reply):
    http, seen = replay(reply())
    with pytest.raises(ProviderError) as e:
        list(TokenFactory(http=http).stream_chat(MSGS))
    assert (e.value.kind, len(seen)) == ("bad_output", 1)


def test_reply_without_choices_is_billed_then_bad_output(replay, recorder):
    calls, on_usage = recorder
    http, _ = replay(httpx.Response(200, json={"model": SUPER, "choices": [],
                                               "usage": {"prompt_tokens": 1000, "completion_tokens": 2000}}))
    with pytest.raises(ProviderError) as e:
        TokenFactory(on_usage=on_usage, http=http).chat(MSGS)
    assert e.value.kind == "bad_output" and len(calls) == 1


def test_stream_chat_yields_deltas_then_bills(replay, recorder):
    calls, on_usage = recorder
    sse = "".join(f"data: {json.dumps(c)}\n\n" for c in [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hel"}}]},
        {"choices": [{"index": 0, "delta": {"content": "lo."}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000}},
    ]) + "data: [DONE]\n\n"
    http, seen = replay(httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
    assert list(TokenFactory(on_usage=on_usage, http=http).stream_chat(MSGS)) == ["Hel", "lo."]
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert calls == [(("token_factory", SUPER, 1000, 2000), {"usd": pytest.approx(SUPER_USD)})]


def test_stream_broken_after_first_chunk_is_a_provider_error(replay):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices": [{"index": 0, "delta": {"content": "Hel"}}]}\n\n'
            raise httpx.RemoteProtocolError("peer closed connection")

    http, seen = replay(httpx.Response(200, stream=Broken()))
    got = []
    with pytest.raises(ProviderError) as e:
        got.extend(TokenFactory(http=http).stream_chat(MSGS))
    assert (got, e.value.kind, len(seen)) == (["Hel"], "server", 1)  # no retry once a chunk went out


# --- files, fine-tuning, LoRA ---------------------------------------------

def test_fine_tuning_routes_and_best_checkpoint(replay, train, ft_priced):
    done = {**JOB, "status": "succeeded", "trained_tokens": 51234, "trained_steps": 12, "total_steps": 12}
    checkpoints = [
        {"id": "ftckpt-1", "step_number": 6, "metrics": {"train_loss": 1.2, "valid_loss": 0.9}, "result_files": ["file-a"]},
        {"id": "ftckpt-2", "step_number": 12, "metrics": {"train_loss": 0.8, "valid_loss": 1.1}, "result_files": ["file-b"]},
    ]
    http, seen = replay(
        httpx.Response(200, json={"id": "file-1", "object": "file", "purpose": "fine-tune", "filename": "train.jsonl"}),
        httpx.Response(200, json=JOB),
        httpx.Response(200, json=done),
        httpx.Response(200, json={"object": "list", "data": [{"created_at": 1, "level": "info", "message": "Job started"}]}),
        httpx.Response(200, json={"object": "list", "data": checkpoints}),
        httpx.Response(200, json={"id": "file-a", "filename": "adapter_model.safetensors"}),
        httpx.Response(200, content=b"\x00adapter"),
        httpx.Response(200, json={"object": "list", "data": [done]}),
        httpx.Response(200, json={**done, "status": "cancelled"}),
    )
    tf = TokenFactory(http=http)
    assert tf.files.create(train) == "file-1"
    hp = {"lora": True, "n_epochs": 2}
    assert tf.fine_tuning.create(LLAMA, "file-1", hyperparameters=hp, suffix="1234abcd-ft")["id"] == "ftjob-7f3a"
    assert tf.fine_tuning.get("ftjob-7f3a")["trained_tokens"] == 51234
    assert tf.fine_tuning.events("ftjob-7f3a")[0]["message"] == "Job started"
    assert tf.fine_tuning.best_checkpoint("ftjob-7f3a")["id"] == "ftckpt-1"  # min valid_loss, not the last
    assert tf.files.get("file-a")["filename"] == "adapter_model.safetensors"
    assert tf.files.content("file-a") == b"\x00adapter"
    assert tf.fine_tuning.list()[0]["id"] == "ftjob-7f3a"
    assert tf.fine_tuning.cancel("ftjob-7f3a")["status"] == "cancelled"
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/v1/files"), ("POST", "/v1/fine_tuning/jobs"), ("GET", "/v1/fine_tuning/jobs/ftjob-7f3a"),
        ("GET", "/v1/fine_tuning/jobs/ftjob-7f3a/events"), ("GET", "/v1/fine_tuning/jobs/ftjob-7f3a/checkpoints"),
        ("GET", "/v1/files/file-a"), ("GET", "/v1/files/file-a/content"), ("GET", "/v1/fine_tuning/jobs"),
        ("POST", "/v1/fine_tuning/jobs/ftjob-7f3a/cancel")]
    assert b'name="purpose"' in seen[0].content and b"fine-tune" in seen[0].content
    assert json.loads(seen[1].content) == {"model": LLAMA, "training_file": "file-1", "hyperparameters": hp,
                                           "suffix": "1234abcd-ft"}
    assert seen[7].url.params["limit"] == "20"


def test_content_follows_the_recorded_307_to_object_storage_without_the_key(replay):
    """Spike 1: the adapter's /content answers 307 to a presigned URL (only its host and a signed query were saved)."""
    hop = recorded("content_redirects")[0]
    location = f"https://{hop['location_host']}/tf-files/{hop['file']}?X-Amz-Signature=presigned"
    http, seen = replay(httpx.Response(hop["status"], headers={"location": location}),
                        httpx.Response(200, content=b"\x00adapter"))
    assert TokenFactory(http=http).files.content(hop["file"]) == b"\x00adapter"
    assert [(r.url.host, r.headers.get("authorization")) for r in seen] == [
        ("api.tokenfactory.nebius.com", "Bearer tf-key"), ("storage.eu-west2.nebius.cloud", None)]


API, STORAGE = "api.tokenfactory.nebius.com", "storage.eu-west2.nebius.cloud"
REFUSED = "token_factory bad_request 307: refused redirect: https only, at most 3 hops"


def redirect(to: str) -> httpx.Response:
    return httpx.Response(307, headers={"location": to}, stream=httpx.ByteStream(b""))  # unread until closed


@pytest.mark.parametrize("target", [f"https://{API}:8443/f", f"http://{API}/f", f"http://{STORAGE}/f"])
def test_content_hops_only_over_https_and_never_with_the_key(replay, target):
    http, seen = replay(redirect(target), httpx.Response(200, content=b"x"))
    if target.startswith("https:"):  # the same host on another port is another origin
        assert TokenFactory(http=http).files.content("file-a") == b"x"
        assert seen[1].headers.get("authorization") is None
    else:
        with pytest.raises(ProviderError) as e:
            TokenFactory(http=http).files.content("file-a")
        assert (str(e.value), len(seen)) == (REFUSED, 1)


def test_content_chain_back_to_token_factory_never_regains_the_key(replay):
    http, seen = replay(redirect(f"https://{STORAGE}/f?X-Amz-Signature=s"), redirect(f"https://{API}/v1/raw/f"),
                        httpx.Response(200, content=b"x"))
    assert TokenFactory(http=http).files.content("file-a") == b"x"
    assert [(r.url.host, r.headers.get("authorization")) for r in seen] == [
        (API, "Bearer tf-key"), (STORAGE, None), (API, None)]


def test_content_redirect_loop_is_refused_after_3_hops(replay):
    hops = [redirect(f"https://{STORAGE}/f") for _ in range(4)]
    http, seen = replay(*hops)
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).files.content("file-a")
    assert (str(e.value), len(seen)) == (REFUSED, 4)
    assert all(r.is_closed for r in hops)


def test_content_redirect_target_error_body_is_not_echoed(replay):
    s3 = "<Error><Code>SignatureDoesNotMatch</Code><SignatureProvided>c2ln</SignatureProvided></Error>"
    http, _ = replay(redirect(f"https://{STORAGE}/f?X-Amz-Signature=c2ln"), httpx.Response(403, text=s3))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).files.content("file-a")
    assert str(e.value) == "token_factory auth 403: the redirect target answered 403"


def test_content_deadline_stops_any_further_send(replay, monkeypatch, sleeps):
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    class Stall(httpx.SyncByteStream):  # a read that times out after the deadline
        def __iter__(self):
            now[0] += 700
            raise httpx.ReadTimeout("stalled")

    http, seen = replay(httpx.Response(200, stream=Stall()))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).files.content("file-a")
    assert (e.value.kind, len(seen), sleeps) == ("server", 1, [])  # no backoff, no second send

    sent = []

    def slow_307(request):  # the deadline passes while Token Factory answers
        sent.append(request)
        now[0] += 700
        return redirect(f"https://{STORAGE}/f")

    with pytest.raises(ProviderError) as e:
        TokenFactory(http=httpx.Client(transport=httpx.MockTransport(slow_307))).files.content("file-a")
    assert (str(e.value), len(sent)) == ("token_factory server None: deadline passed before the next send", 1)


def test_content_cut_off_mid_body_is_retried_like_any_timeout(replay, sleeps):
    class Cut(httpx.SyncByteStream):
        def __iter__(self):
            yield b"\x00ada"
            raise httpx.ReadTimeout("stalled")

    http, seen = replay(httpx.Response(200, stream=Cut()), httpx.Response(200, content=b"\x00adapter"))
    assert TokenFactory(http=http).files.content("file-a") == b"\x00adapter"
    assert (len(seen), len(sleeps)) == (2, 1)
    http, seen = replay(*[httpx.Response(200, stream=Cut()) for _ in range(4)])
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).files.content("file-a")
    assert (e.value.kind, len(seen)) == ("server", 4)


def test_content_is_bounded_in_size_and_time(replay, monkeypatch):
    monkeypatch.setattr(tokenfactory, "FILE_MAX_BYTES", 4)
    pulled = []

    class Long(httpx.SyncByteStream):  # aborting mid-stream stops pulling; reading it all, then checking, would not
        def __iter__(self):
            for i in range(1000):
                pulled.append(i)
                yield b"xx"

    http, _ = replay(httpx.Response(200, content=b"1234"), httpx.Response(200, stream=Long()))
    tf = TokenFactory(http=http)
    assert tf.files.content("file-a") == b"1234"
    with pytest.raises(ProviderError) as e:
        tf.files.content("file-a")
    assert (e.value.kind, len(pulled)) == ("bad_output", 3)

    now = [0.0]

    class Slow(httpx.SyncByteStream):  # each chunk lands 6 s after the last: inside the read timeout, past the deadline
        def __iter__(self):
            for _ in range(3):
                now[0] += 6
                yield b"x"

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tokenfactory, "FILE_TIMEOUT_S", 10)
    http, seen = replay(httpx.Response(200, stream=Slow()))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).files.content("file-a")
    assert (e.value.kind, len(seen)) == ("server", 1)


def test_best_checkpoint_without_valid_loss_is_the_last_step(replay):
    data = [{"id": "c1", "step_number": 1, "metrics": {"train_loss": 1.0}}, {"id": "c2", "step_number": 2, "metrics": {}}]
    http, _ = replay(httpx.Response(200, json={"data": data}))
    assert TokenFactory(http=http).fine_tuning.best_checkpoint("ftjob-1")["id"] == "c2"


def test_lora_deploy_returns_the_model_name_to_chat_with(replay):
    served = f"{LLAMA}-LoRa:orchapod-1234abcd-AbCd"
    http, seen = replay(httpx.Response(200, json={"name": served, "base_model": LLAMA, "status": "validating"}),
                        httpx.Response(200, json={"name": served, "status": "active"}),
                        httpx.Response(200, json={}))
    tf = TokenFactory(http=http)
    assert tf.lora.deploy("orchapod-1234abcd", LLAMA, "ftjob-7f3a:ftckpt-2") == served
    assert tf.lora.status(served) == "active"
    tf.lora.delete(served)
    assert str(seen[0].url) == "https://api.tokenfactory.nebius.com/v0/models"
    assert json.loads(seen[0].content) == {"name": "orchapod-1234abcd", "base_model": LLAMA, "source": "ftjob-7f3a:ftckpt-2"}
    assert [r.method for r in seen] == ["POST", "GET", "DELETE"] and seen[2].url.path == f"/v0/models/{served}"


@pytest.mark.parametrize("status", [400, 404, 405, 422])
def test_lora_deploy_rejected_is_unsupported(replay, status):
    http, seen = replay(httpx.Response(status, json={"detail": "Not Found"}))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).lora.deploy("orchapod-1234abcd", LLAMA, "ftjob-7f3a:ftckpt-2")
    assert e.value.kind == "unsupported" and len(seen) == 1
    assert (f"Token Factory has no per-token LoRA deploy for {LLAMA} ({status}): "
            "serve lora_adapter with vllm-serve") in str(e.value)


def test_lora_deploy_retired_410_is_unsupported(replay):
    """Spike 1: POST /v0/models, sent as tf-deploy sends it, answers 410 for every base (deploy_result.json)."""
    gone = recorded("deploy_result")
    http, seen = replay(httpx.Response(gone["status"], text=gone["body"]))
    with pytest.raises(ProviderError) as e:
        TokenFactory(http=http).lora.deploy(**recorded("deploy_request"))
    assert (e.value.kind, e.value.status, len(seen)) == ("unsupported", 410, 1)
    assert str(e.value) == ("token_factory unsupported 410: Token Factory has no per-token LoRA deploy for "
                            f"{LLAMA} (410): serve lora_adapter with vllm-serve; Token Factory said: {gone['body']}")


# --- STUB=1 ---------------------------------------------------------------

def test_stub_is_deterministic_and_offline(monkeypatch, train, recorder, replay):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")  # no key needed, nothing sent
    calls, on_usage = recorder
    tf = TokenFactory(on_usage=on_usage)
    a, b = tf.chat(MSGS, LLAMA), TokenFactory().chat(MSGS, LLAMA)  # unpriced is fine: nothing is spent
    assert a == b and a["text"].startswith("stub-") and len(a["text"]) == 13
    assert tf.chat([{"role": "user", "content": "other"}], LLAMA)["text"] != a["text"]
    http, seen = replay()
    assert TokenFactory(http=http).chat(MSGS, LLAMA) == a and seen == []  # STUB wins over an injected client
    assert (a["in_tokens"], a["out_tokens"], a["usd"]) == (0, 0, 0)
    assert calls[0] == (("token_factory", LLAMA, 0, 0), {"usd": 0.0})

    schema = {"type": "object", "properties": {
        "pairs": {"type": "array", "items": {"type": "object", "properties": {"q": {"type": "string"}, "n": {"type": "integer"}}}},
        "winner": {"enum": ["A", "B", "tie"]}, "ok": {"type": "boolean"}, "why": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    parsed = tf.chat(MSGS, json_schema=schema)["parsed"]
    h = parsed["why"]
    assert parsed == {"pairs": [{"q": h, "n": 0}], "winner": "A", "ok": False, "why": h} and h.startswith("stub-")
    streamed = "".join(tf.stream_chat(MSGS, LLAMA))
    assert streamed == "".join(tf.stream_chat(MSGS, LLAMA)) and streamed.startswith("stub-")

    file_id = tf.files.create(train)
    assert file_id == TokenFactory().files.create(train) and "-stub-" in file_id
    job = tf.fine_tuning.create(LLAMA, file_id, hyperparameters={"lora": True})
    assert "-stub-" in job["id"] and job["status"] == "succeeded"
    assert tf.fine_tuning.get(job["id"])["status"] == "succeeded"
    cps = tf.fine_tuning.checkpoints(job["id"])
    assert [(c["step_number"], c["metrics"]["valid_loss"]) for c in cps] == [(1, 1.0), (2, 0.5)]
    assert tf.fine_tuning.best_checkpoint(job["id"])["step_number"] == 2
    name = tf.lora.deploy("orchapod-1234abcd", LLAMA, f"{job['id']}:{cps[1]['id']}")
    assert tf.lora.status(name) == "active"
