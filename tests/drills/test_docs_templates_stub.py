"""The docs-specialist templates (Lane B on an endpoint, and its CPU variant) run end to end in STUB at reduced scale through
the API and the executor, each node's own run.py in this process with the real SDK (the drills' harness): no Docker, no
network. Proves the templates' refs resolve into the inputs each node reads. Since backend-w8 the Docker stub e2e can run
them too: under STUB, plan review skips the GPU-provider check and the executor runs unsloth-train (a GPU node) on
LocalDocker, from the image built with `--target stub` (containers/unsloth-train/Dockerfile's slim first stage)."""

import pytest

from api.agent import planner
from api.routes import internal
from tests.containers.conftest import load_container
from tests.drills.test_failure_drills import ADMIN, BUCKET, bucket, drill, env  # noqa: F401 (fixtures)

NANO = "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"


@pytest.mark.parametrize("slug", ["nebius-docs-specialist", "nebius-docs-specialist-cpu"])
async def test_a_docs_template_runs_end_to_end_in_stub(drill, monkeypatch, tmp_path, slug):  # noqa: F811 (fixture)
    monkeypatch.setenv("STUB", "1")
    for node, workspace in (("unsloth-train", "WORK"), ("quantize", "WORKSPACE_DIR")):  # /workspace in their images
        monkeypatch.setattr(load_container(node), workspace, tmp_path / node)
    armed = []  # vllm-serve registers its stub endpoint; the expiry timer would outlive the test
    monkeypatch.setattr(internal, "_arm", lambda artifact, run_id: armed.append(artifact.meta["endpoint_id"]))
    t = next(t for t in planner.templates() if t["slug"] == slug)

    s = await drill.run(planner.reduced(t)["plan"]["nodes"], headers=ADMIN)  # unsloth-train rents a GPU: admin only

    assert (s["status"], s["error"]) == ("succeeded", None), [(n["node_id"], n["error"]) for n in s["nodes"]]
    made = {(a["node_id"], a["name"]): a for a in s["artifacts"]}
    summary = made[("evaluate", "eval_summary")]["meta"]
    assert summary["stub"] is True and summary["n"] >= 1 and summary["errors"] == 0
    run = made[("evaluate", "eval_summary")]["uri"].split("/")[-3]
    if slug.endswith("-cpu"):  # tuned = the student's GGUF plus its GGUF LoRA, served by judge-eval's llama-server
        gguf, lora = (f"r2://{BUCKET}/runs/{run}/quantize/{name}" for name in ("gguf_file", "gguf_lora"))
        assert made[("quantize", "gguf_lora")]["meta"]["type"] == "lora"
        assert (summary["base"]["model"], summary["tuned"]["model"], summary["tuned"]["base_model"]) == (gguf, lora, gguf)
    else:  # base and tuned from one endpoint
        assert armed and (summary["base"]["model"], summary["tuned"]["model"]) == (NANO, "tuned")
        assert summary["tuned"]["api_key_env"] == summary["base"]["api_key_env"] == "ORCHAPOD_ENDPOINT_TOKEN"
