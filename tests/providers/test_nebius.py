"""NebiusServerless (Jobs, Endpoints) and NebiusProvider against faked REST replies in the shapes of
https://docs.nebius.com/serverless/jobs/manage and /serverless/endpoints/manage (no live calls)."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from packages.providers import nebius
from packages.providers.base import GPUSpec, Pod, ProviderError, ProvisionError
from packages.providers.nebius import AI_BASE, NebiusProvider, NebiusServerless

GIB = 2 ** 30
PROJECT = "project-e00abc"
R2 = {"ORCHAPOD_R2_ENDPOINT": "https://storage.eu-north1.nebius.cloud", "ORCHAPOD_R2_REGION": "eu-north1",
      "ORCHAPOD_R2_ACCESS_KEY": "r2-access", "ORCHAPOD_R2_SECRET_KEY": "r2-secret"}
JOB_ENV = {"ORCHAPOD_CONTROL_URL": "https://api.orchapod.example", "ORCHAPOD_R2_ENDPOINT": R2["ORCHAPOD_R2_ENDPOINT"],
           "ORCHAPOD_RUN_ID": "9214965e-1c2d-4e5f-8a9b-0c1d2e3f4a5b", "ORCHAPOD_NODE_ID": "train", "STUB": "",
           "ORCHAPOD_MAX_COST_USD": "3.0000", "NEBIUS_IAM_TOKEN": "iam-secret"}


@pytest.fixture(autouse=True)
def nebius_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEBIUS_PROJECT_ID", PROJECT)
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "iam-token-0")
    for name, value in R2.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # no nebius CLI unless a test installs the fake one


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """A fake `nebius` CLI on PATH: it prints a notice, then iam-token-<n> on its n-th run. Returns its log of runs."""
    runs = tmp_path / "bin" / "runs"
    runs.parent.mkdir()
    script = runs.parent / "nebius"
    script.write_text(f'#!/bin/sh\necho "$*" >> "{runs}"\necho "A newer nebius CLI is available."\n'
                      f'echo "iam-token-$(grep -c . "{runs}")"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{runs.parent}:/usr/bin:/bin")
    return runs


@pytest.fixture
def polls(monkeypatch):
    """A fake clock for the provider: its asyncio.sleep calls are recorded and advance nebius.monotonic, never slept."""
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(nebius, "monotonic", lambda: sum(slept))
    return slept


def op(resource_id="aijob-e00job1"):
    """The Operation a create, cancel or delete returns; resourceId is the job or endpoint id."""
    return httpx.Response(200, json={"id": "aiop-e00op1", "createdAt": "2026-10-21T10:00:00Z",
                                     "createdBy": "serviceaccount-e00sa", "resourceId": resource_id})


def item(id, state, *, name="orchapod-run", public=(), code=None, message=None):
    """A Job or Endpoint as GET returns it (nebius/ai/v1/job.proto, endpoint.proto in proto3 JSON)."""
    status = {"state": state, "publicEndpoints": list(public)}
    if code:
        status["stateDetails"] = {"code": code, "message": message}
    return {"metadata": {"id": id, "parentId": PROJECT, "name": name, "createdAt": "2026-10-21T10:00:00Z"},
            "spec": {}, "status": status}


def page(*names):
    return httpx.Response(200, json={"items": [item(f"aiendpoint-{n}", "RUNNING", name=n) for n in names]})


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def create_job(serverless: NebiusServerless) -> str:
    return serverless.jobs.create("orchapod-run", "img", env={}, platform="gpu-l40s-a", preset="1gpu-8vcpu-32gb")


# --- NebiusServerless -----------------------------------------------------

def test_jobs_create_posts_the_documented_job(replay):
    http, seen = replay(op("aijob-e00job1"))
    job_id = NebiusServerless(http=http).jobs.create(
        "orchapod-run", "ghcr.io/bangadpurva/unsloth-train:latest", args="--max-steps 60",
        env={"HF_TOKEN": "hf-1", "STUB": ""}, platform="gpu-l40s-a", preset="1gpu-8vcpu-32gb",
        volumes=("s3://orchapod-artifacts:/mnt/artifacts:ro",))
    assert job_id == "aijob-e00job1"
    request = seen[0]
    assert (request.method, str(request.url), request.headers["authorization"]) == (
        "POST", f"{AI_BASE}/jobs", "Bearer iam-token-0")
    assert body(request) == {"metadata": {"parentId": PROJECT, "name": "orchapod-run"}, "spec": {
        "image": "ghcr.io/bangadpurva/unsloth-train:latest", "args": "--max-steps 60",
        "environmentVariables": [{"name": "HF_TOKEN", "value": "hf-1"}],  # blank values are not sent
        "platform": "gpu-l40s-a", "preset": "1gpu-8vcpu-32gb", "timeout": "3600s",
        "disk": {"type": "NETWORK_SSD", "sizeBytes": str(250 * GIB)}, "shmSizeBytes": str(16 * GIB),
        "volumes": [{"source": "s3://orchapod-artifacts", "containerPath": "/mnt/artifacts", "mode": "READ_ONLY",
                     "s3Config": {"endpoint": R2["ORCHAPOD_R2_ENDPOINT"], "region": "eu-north1",
                                  "credentials": {"accessKeyId": "r2-access", "secretAccessKey": "r2-secret"}}}]}}


def test_endpoints_create_exposes_one_http_port_behind_the_auth_token(replay):
    http, seen = replay(op("aiendpoint-e00ep1"))
    endpoint_id = NebiusServerless(http=http).endpoints.create(
        "orchapod-serve", "vllm/vllm-openai:v0.18.0-cu130", args="Qwen/Qwen3-0.6B --port 8000", env={},
        platform="gpu-l40s-a", preset="1gpu-8vcpu-32gb", auth_token="ep-token",
        volumes=("s3://orchapod-artifacts:/mnt/artifacts:rw",))
    assert endpoint_id == "aiendpoint-e00ep1" and str(seen[0].url) == f"{AI_BASE}/endpoints"
    spec = body(seen[0])["spec"]
    assert (spec["ports"], spec["authToken"], spec["volumes"][0]["mode"]) == (
        [{"containerPort": 8000, "protocol": "HTTP"}], "ep-token", "READ_WRITE")
    assert (spec["disk"], spec["shmSizeBytes"]) == ({"type": "NETWORK_SSD", "sizeBytes": str(250 * GIB)}, str(16 * GIB))
    assert "timeout" not in spec  # a Job's field


def test_get_reads_the_state_its_cause_and_the_https_url_once_running(replay):
    public = ["http://plain.example", "203.0.113.7:8000", "tls://ep-e00ep1.example:443", "https://ep-e00ep1.example"]
    http, seen = replay(httpx.Response(200, json=item("aiendpoint-e00ep1", "STARTING", public=public)),
                        httpx.Response(200, json=item("aiendpoint-e00ep1", "RUNNING", public=public)),
                        httpx.Response(200, json=item("aijob-e00job1", "ERROR", code="NotEnoughResources",
                                                      message="Due to high demand, we can't start this workload.")))
    serverless = NebiusServerless(http=http)
    assert serverless.endpoints.get("aiendpoint-e00ep1")["url"] is None  # None until RUNNING
    assert serverless.endpoints.get("aiendpoint-e00ep1") == {  # https only
        "id": "aiendpoint-e00ep1", "name": "orchapod-run", "state": "RUNNING", "url": "https://ep-e00ep1.example",
        "code": None, "message": None}
    assert serverless.jobs.get("aijob-e00job1") == {
        "id": "aijob-e00job1", "name": "orchapod-run", "state": "ERROR", "url": None, "code": "NotEnoughResources",
        "message": "Due to high demand, we can't start this workload."}
    assert [str(r.url) for r in seen] == [f"{AI_BASE}/endpoints/aiendpoint-e00ep1"] * 2 + [f"{AI_BASE}/jobs/aijob-e00job1"]


def test_cancel_and_delete_take_the_documented_routes_and_a_404_delete_is_done(replay):
    http, seen = replay(op(), op(), httpx.Response(404, json={"code": 5, "message": "endpoint not found"}))
    serverless = NebiusServerless(http=http)
    serverless.jobs.cancel("aijob-e00job1")
    serverless.jobs.delete("aijob-e00job1")
    serverless.endpoints.delete("aiendpoint-e00gone")  # already gone
    assert [(r.method, str(r.url)) for r in seen] == [("POST", f"{AI_BASE}/jobs/cancel"),
                                                      ("DELETE", f"{AI_BASE}/jobs/aijob-e00job1"),
                                                      ("DELETE", f"{AI_BASE}/endpoints/aiendpoint-e00gone")]
    assert body(seen[0]) == {"id": "aijob-e00job1"}


def test_list_pages_through_the_whole_project(replay):
    http, seen = replay(httpx.Response(200, json={"nextPageToken": "page-2", "items": [
        item("aiendpoint-e00a", "RUNNING", name="orchapod-a", public=["https://a"])]}), page("b"))
    endpoints = NebiusServerless(http=http).endpoints.list()
    assert [(e["id"], e["name"], e["state"], e["url"]) for e in endpoints] == [
        ("aiendpoint-e00a", "orchapod-a", "RUNNING", "https://a"), ("aiendpoint-b", "b", "RUNNING", None)]
    assert [(r.url.path, dict(r.url.params)) for r in seen] == [
        ("/ai/v1/endpoints", {"parentId": PROJECT}), ("/ai/v1/endpoints", {"parentId": PROJECT, "pageToken": "page-2"})]


def test_find_looks_at_about_0_15_and_45_s_and_a_failed_lookup_is_a_miss(replay, sleeps):
    http, seen = replay(page("other"), httpx.Response(403, json={"code": 7, "message": "denied"}), page("other", "mine"),
                        page(), page(), page())
    endpoints = NebiusServerless(http=http).endpoints
    assert endpoints.find("mine")["id"] == "aiendpoint-mine" and sleeps == [0, 15, 30]
    sleeps.clear()
    assert endpoints.find("gone") is None and sleeps == [0, 15, 30] and len(seen) == 6


@pytest.mark.parametrize("answers, sent", [
    ((httpx.Response(503, text="unavailable"),), 1),  # it may have landed: never re-sent
    ((httpx.ReadTimeout("slow"),), 1),
    ((httpx.Response(429, json={"code": 8, "message": "quota"}), op()), 2),  # refused before anything ran
    ((httpx.ConnectError("refused"), op()), 2),
], ids=["5xx", "read_timeout", "429", "connect_error"])
def test_a_create_is_sent_again_only_when_it_cannot_have_landed(replay, answers, sent):
    http, seen = replay(*answers)
    if sent == 1:
        with pytest.raises(ProviderError) as e:
            create_job(NebiusServerless(http=http))
        assert e.value.kind == "server"
    else:
        assert create_job(NebiusServerless(http=http)) == "aijob-e00job1"
    assert len(seen) == sent


def test_a_create_reply_without_an_id_is_bad_output_so_the_caller_looks_it_up_by_name(replay):
    http, seen = replay(httpx.Response(200, json={"id": "aiop-e00op1", "createdBy": "serviceaccount-e00sa"}))
    with pytest.raises(ProviderError) as e:
        create_job(NebiusServerless(http=http))
    assert (e.value.kind, len(seen)) == ("bad_output", 1)


@pytest.mark.parametrize("env, volume", [
    ({"NEBIUS_PROJECT_ID": ""}, "s3://b:/mnt:ro"),
    ({"ORCHAPOD_R2_ENDPOINT": "http://localhost:9000"}, "s3://b:/mnt:ro"),  # Nebius cannot mount a local MinIO
    ({}, "s3://b/mnt:ro"), ({}, "s3://b:/mnt"), ({}, "storagebucket-e00b:/mnt:ro")])
def test_no_project_a_local_bucket_or_a_volume_not_in_the_cli_form_is_refused_before_sending(replay, monkeypatch, env,
                                                                                             volume):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        NebiusServerless(http=http).jobs.create("n", "img", env={}, platform="p", preset="p", volumes=(volume,))
    assert (e.value.kind, seen) == ("bad_request", []) and "localhost" not in str(e.value)


def test_an_endpoint_without_an_auth_token_is_refused_because_nebius_would_leave_it_open(replay):
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        NebiusServerless(http=http).endpoints.create("e", "img", env={}, platform="p", preset="p", auth_token="")
    assert (e.value.kind, seen) == ("bad_request", [])


def test_no_token_and_no_cli_is_auth_before_anything_is_sent(replay, monkeypatch):
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "")
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        NebiusServerless(http=http).endpoints.get("aiendpoint-e00ep1")
    assert (e.value.kind, seen) == ("auth", []) and "nebius CLI" in e.value.message


@pytest.mark.parametrize("env_token", ["", "not a token"])
def test_an_empty_or_malformed_token_runs_the_cli_once_and_keeps_its_last_line(replay, cli, monkeypatch, env_token):
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", env_token)
    http, seen = replay(*[httpx.Response(200, json=item("aijob-e00job1", "RUNNING")) for _ in range(2)])
    serverless = NebiusServerless(http=http)
    assert [serverless.jobs.get("aijob-e00job1")["state"] for _ in range(2)] == ["RUNNING", "RUNNING"]
    assert cli.read_text() == "iam get-access-token\n"
    assert [r.headers["authorization"] for r in seen] == ["Bearer iam-token-1"] * 2


def test_cli_output_that_is_not_a_token_is_auth_with_a_fixed_message(replay, cli, monkeypatch):
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "")
    (cli.parent / "nebius").write_text('#!/bin/sh\necho "eyJ-secret part1"\n')  # a header with a space: never sent
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        NebiusServerless(http=http).jobs.get("aijob-e00job1")
    assert (e.value.kind, seen) == ("auth", []) and "secret" not in str(e.value)


def test_a_401_renews_the_token_once_and_sends_the_call_again(replay, cli):
    def unauthenticated():
        return httpx.Response(401, json={"code": 16, "message": "token expired"})

    http, seen = replay(unauthenticated(), op(), unauthenticated(), unauthenticated())
    serverless = NebiusServerless(http=http)
    assert create_job(serverless) == "aijob-e00job1"  # a 401 is refused before anything runs, so a create may go again
    with pytest.raises(ProviderError) as e:
        serverless.jobs.delete("aijob-e00job1")
    assert (e.value.kind, e.value.status) == ("auth", 401)  # the renewed token was refused too: no loop
    assert [r.headers["authorization"] for r in seen] == [
        "Bearer iam-token-0", "Bearer iam-token-1", "Bearer iam-token-1", "Bearer iam-token-2"]
    assert cli.read_text() == "iam get-access-token\n" * 2


def test_stub_answers_offline_jobs_complete_and_endpoints_run_at_stub_invalid(monkeypatch):
    def network(*_):
        raise AssertionError("STUB reached the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", network)
    for name, value in (("STUB", "1"), ("NEBIUS_IAM_TOKEN", ""), ("NEBIUS_PROJECT_ID", ""),
                        ("ORCHAPOD_R2_ENDPOINT", "http://localhost:9000")):  # the compose MinIO is fine offline
        monkeypatch.setenv(name, value)
    serverless = NebiusServerless()
    job_id = create_job(serverless)
    assert job_id.startswith("aijob-stub-") and job_id == create_job(NebiusServerless())  # deterministic per request
    assert serverless.jobs.get(job_id)["state"] == "COMPLETED"
    endpoint_id = serverless.endpoints.create("e", "img", env={}, platform="p", preset="p", auth_token="t",
                                              volumes=("s3://orchapod-artifacts:/mnt/artifacts:ro",))
    assert {k: v for k, v in serverless.endpoints.get(endpoint_id).items() if k in ("id", "state", "url")} == {
        "id": endpoint_id, "state": "RUNNING", "url": "http://stub.invalid"}
    assert serverless.jobs.list() == serverless.endpoints.list() == []
    serverless.jobs.cancel(job_id)
    serverless.jobs.delete(job_id)
    serverless.endpoints.delete(endpoint_id)


# --- NebiusProvider -------------------------------------------------------

@pytest.mark.parametrize("gpu, platform, preset", [("H100", "gpu-h100-sxm", "1gpu-16vcpu-200gb"),
                                                   ("L40S", "gpu-l40s-a", "1gpu-8vcpu-32gb")])
async def test_provision_runs_the_node_as_one_job_without_the_iam_token(replay, gpu, platform, preset):
    http, seen = replay(op("aijob-e00job1"))
    pod = await NebiusProvider(http=http).provision(GPUSpec(gpu_type=gpu), "ghcr.io/bangadpurva/unsloth-train:latest",
                                                    JOB_ENV)
    assert pod == Pod(provider="nebius", pod_id="aijob-e00job1")
    sent = body(seen[0])
    assert re.fullmatch(r"orchapod-9214965e-\d{10}-train", sent["metadata"]["name"])
    spec = sent["spec"]
    assert (spec["image"], spec["platform"], spec["preset"], spec["timeout"]) == (
        "ghcr.io/bangadpurva/unsloth-train:latest", platform, preset, "3600s")
    names = {v["name"] for v in spec["environmentVariables"]}
    assert "ORCHAPOD_NODE_ID" in names and "NEBIUS_IAM_TOKEN" not in names  # gpu jobs never call the Nebius API


async def test_provision_refuses_a_control_plane_or_bucket_the_job_cannot_reach(replay):
    http, seen = replay()
    for name, value in (("ORCHAPOD_CONTROL_URL", "http://localhost:8001"), ("ORCHAPOD_R2_ENDPOINT", "http://10.0.0.5:9000")):
        with pytest.raises(ProvisionError, match=name) as e:
            await NebiusProvider(http=http).provision(GPUSpec(gpu_type="H100"), "img", {**JOB_ENV, name: value})
        assert value not in str(e.value)  # anonymous viewers read node errors
    for spec in (GPUSpec(gpu_type="H200"), GPUSpec(gpu_type="H100", count=2)):
        with pytest.raises(LookupError, match="1xH100 or 1xL40S"):
            await NebiusProvider(http=http).provision(spec, "img", JOB_ENV)
    assert seen == []


async def test_provision_adopts_its_job_once_find_sees_it_after_a_lost_reply(sleeps):
    sent = []

    def nebius_api(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "POST":  # DEADLINE_EXCEEDED: "may occur even if the request completed successfully"
            return httpx.Response(504, json={"code": 4, "message": "deadline exceeded"})
        mine = [item("aijob-e00mine", "PROVISIONING", name=body(sent[0])["metadata"]["name"])] if len(sent) > 2 else []
        return httpx.Response(200, json={"items": [item("aijob-e00other", "RUNNING", name="orchapod-other"), *mine]})

    provider = NebiusProvider(http=httpx.Client(transport=httpx.MockTransport(nebius_api)))
    pod = await provider.provision(GPUSpec(gpu_type="L40S"), "img", JOB_ENV)
    assert pod.pod_id == "aijob-e00mine" and [r.method for r in sent] == ["POST", "GET", "GET"] and sleeps == [0, 15]


async def test_provision_names_the_job_when_a_lost_create_never_shows_up(replay, sleeps):
    http, seen = replay(httpx.ReadTimeout("slow"), page(), page(), page())
    with pytest.raises(ProvisionError) as e:
        await NebiusProvider(http=http).provision(GPUSpec(gpu_type="H100"), "img", JOB_ENV)
    name = body(seen[0])["metadata"]["name"]
    assert str(e.value).endswith(f"job {name} may still exist, cancel it in the console")
    assert isinstance(e.value.__cause__, ProviderError) and sleeps == [0, 15, 30] and len(seen) == 4


async def test_provision_looks_nothing_up_after_a_refused_create(replay):
    http, seen = replay(httpx.Response(400, json={"code": 3, "message": "unknown preset"}))
    with pytest.raises(ProviderError) as e:
        await NebiusProvider(http=http).provision(GPUSpec(gpu_type="H100"), "img", JOB_ENV)
    assert (e.value.kind, len(seen)) == ("bad_request", 1)


async def test_wait_polls_every_15_s_through_api_blips_and_keeps_the_failure_reason(replay, polls, caplog):
    http, _ = replay(
        httpx.Response(200, json=item("aijob-e00job1", "PROVISIONING")),
        *[httpx.Response(503, text="unavailable") for _ in range(4)],  # outlasts the client's 3 retries
        httpx.Response(200, json=item("aijob-e00job1", "RUNNING")),
        httpx.Response(200, json=item("aijob-e00job1", "COMPLETED")),
        httpx.Response(200, json=item("aijob-e00job2", "FAILED", code="ContainerFailed",
                                      message="exit code 1, see https://console.nebius.com/jobs/aijob-e00job2")))
    provider = NebiusProvider(http=http)
    done, failed = Pod(provider="nebius", pod_id="aijob-e00job1"), Pod(provider="nebius", pod_id="aijob-e00job2")
    assert await provider.wait(done) == 0 and done.error is None
    assert polls == [15, 15, 15]
    assert await provider.wait(failed) == 1
    assert failed.error == "FAILED ContainerFailed: exit code 1, see <url>"  # backend shows it instead of "exit 1"
    assert "aijob-e00job2 FAILED: ContainerFailed exit code 1" in caplog.text


async def test_wait_stops_once_the_jobs_spend_reaches_the_nodes_budget(replay, polls):
    http, seen = replay(op("aijob-e00job1"), *[httpx.Response(200, json=item("aijob-e00job1", "RUNNING")) for _ in range(4)])
    provider = NebiusProvider(http=http)
    env = {**JOB_ENV, "ORCHAPOD_MAX_COST_USD": "0.0500"}  # $4.50 an hour: the cap is reached after 40 s
    pod = await provider.provision(GPUSpec(gpu_type="H100"), "img", env)
    assert await provider.wait(pod) == 1
    assert polls == [15, 15, 15] and len(seen) == 5  # create, then polls at 0, 15, 30 and 45 s
    assert pod.error == "budget: node cap $0.05 reached (gpu-h100-sxm at $4.50/h)"


async def test_terminate_cancels_then_deletes_even_when_the_job_already_ended(replay):
    http, seen = replay(httpx.Response(400, json={"code": 9, "message": "job is not running"}), op())
    await NebiusProvider(http=http).terminate(Pod(provider="nebius", pod_id="aijob-e00job1"))
    assert [(r.method, r.url.path) for r in seen] == [("POST", "/ai/v1/jobs/cancel"), ("DELETE", "/ai/v1/jobs/aijob-e00job1")]


async def test_stream_logs_yields_nothing_because_jobs_have_no_rest_logs():
    assert [line async for line in NebiusProvider().stream_logs(Pod(provider="nebius", pod_id="aijob-e00job1"))] == []
