# Node I/O Contract

**This is the most important document in the repo.**
Get this right and adding a new node is a 1-day task.
Break this and the entire DAG execution falls apart.

## The contract

Every node is a Docker container that:
1. Reads its inputs from environment variables
2. Does its ML work (train, quantize, evaluate, etc.)
3. Writes outputs to local disk
4. Uploads outputs to R2 via the SDK
5. Notifies the control plane via webhook
6. Exits with code 0 (success) or non-zero (failure)

## Environment variables injected by the executor

| Variable | Contents |
|----------|----------|
| `ORCHAPOD_NODE_INPUTS` | JSON-encoded dict of resolved inputs (URIs + scalars) |
| `ORCHAPOD_NODE_OUTPUTS_DIR` | Local path where the node writes output files |
| `ORCHAPOD_RUN_ID` | UUID of the parent run |
| `ORCHAPOD_NODE_ID` | Node ID from YAML, e.g. `fine_tune_1` |
| `ORCHAPOD_R2_ENDPOINT` | R2/S3 endpoint URL |
| `ORCHAPOD_R2_ACCESS_KEY` | R2 access key |
| `ORCHAPOD_R2_SECRET_KEY` | R2 secret key |
| `ORCHAPOD_R2_BUCKET` | R2 bucket name |
| `ORCHAPOD_CONTROL_URL` | Control plane webhook base URL |
| `ORCHAPOD_RESUME_CHECKPOINT_URI` | R2 URI of checkpoint to resume from (optional; set on retry) |
| `ORCHAPOD_R2_REGION` | Object storage region (`auto` for MinIO/R2, `eu-north1` on Nebius) |
| `ORCHAPOD_INTERNAL_SECRET` | Sent by the SDK as `X-Orchapod-Secret` on every /internal call |
| `ORCHAPOD_MAX_COST_USD` | Node budget: the smaller of the run and day budgets left; `cost.add` raises `BudgetExceeded` past it |
| `STUB` | `1` = deterministic outputs, no paid calls |
| Provider keys | `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `TAVILY_API_KEY`, `HF_TOKEN`, `NEBIUS_PROJECT_ID`, `NEBIUS_IAM_TOKEN`, `ORCHAPOD_ENDPOINT_TOKEN` (docs/contracts.md "Config") |

## Artifact addressing

All artifacts are stored in R2 at:
```
runs/{run_id}/{node_id}/{artifact_name}
```

R2 URI format: `r2://${ORCHAPOD_R2_BUCKET}/runs/{run_id}/{node_id}/{artifact_name}`. Names match `^[a-z][a-z0-9_]*$` (refs split on dots); `write_output` rejects anything else.

## Standard run.py template

```python
from orchapod import io, log

def main():
    inputs = io.read_inputs()
    log.info(f"Node started with inputs: {list(inputs.keys())}")

    # ... do the work ...

    output_path = io.local_path("my_output")
    # write to output_path ...

    # SDK handles upload to R2 + control-plane notification
    io.write_output(
        name="my_output",
        local_path=output_path,
        kind="model",           # dataset | model | metrics | log | endpoint
        metadata={"key": "val"},
    )

    log.info("Node complete")

if __name__ == "__main__":
    main()
```

## Calling Token Factory and Tavily

Only through `packages.providers`: `TokenFactory(on_usage=cost.add).chat(messages, model, json_schema=schema)` and `Tavily(on_usage=cost.add).extract(urls)`. The clients own retries, the $ of every call (`orchapod.prices.PRICES`; an unpriced model is refused before anything is sent), the rule that `NEBIUS_API_KEY` only goes to `NEBIUS_BASE_URL`, and `STUB=1` (deterministic fakes, no network). Every failure is a `ProviderError`; log `str(e)` as the node's last ERROR line.

Cost, metrics and exit (docs/contracts.md "Node SDK"): record each billed call with `cost.add(provider, model, in_tokens, out_tokens, usd=None, **extra)` (clients take `on_usage=cost.add`) and call `io.write_metrics({...})` once. After `io.read_inputs()` the SDK writes `cost_json` at any exit: normal, an uncaught exception (logged as ERROR) or SIGTERM, which it raises as `SystemExit(143)` so your `finally` blocks run — cancel remote jobs there. Then it writes `logs` (kind `log`): the last 5,000 lines the node logged through `log`, as JSONL `{ts, level, message}`, so a finished run keeps its logs after the live stream is gone. The name `logs` is reserved: `write_output` refuses it. Cancel and the `ORCHAPOD_NODE_TIMEOUT_S` backstop (5400 s) send SIGTERM and kill after 30 s; a failed node's error is `exit <code>: <last log.error line>`; `POST /runs/{id}/nodes/{node_id}/retry` re-runs the same NodeRun and continues downstream.

## Adding a new node

1. Create `containers/{node-name}/Dockerfile`; the build context is the repo root, so it does `COPY packages/sdk-py/orchapod /app/orchapod` and `COPY containers/{node-name}/run.py /app/run.py` (enforced by `tests/containers/test_dockerfiles.py`)
2. Create `containers/{node-name}/run.py` (follow template above)
3. Add input/output schemas to `packages/workflow_schema/models.py`
4. Register in `NODE_REGISTRY` in the same file
5. Build and push: `bash scripts/build-and-push-containers.sh` (it builds every `containers/*/Dockerfile` and pushes to `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}`, so there is no node list to update)
6. Add `{node-name}` to the `containers` matrix in `.github/workflows/ci.yml` (a test fails if it is missing): CI pushes `ghcr.io/bangadpurva/{node-name}:latest` from NebiusHackathon, the image the executor pulls (contracts R4)
7. `make check E2E=1` also runs the stub e2e of intent #2 (`scripts/e2e_demo.py --stub --strict`; needs Docker and `make up`; orchestrator/integration only, because it rebuilds and retags the shared `orchapod/<node>:dev` images): it rebuilds every node of that template from your tree, runs them through the API and asserts the artifacts and a $0 cost

Local runs use `orchapod/<node>:dev` when that image exists (`docker build -t orchapod/<node>:dev -f containers/<node>/Dockerfile .`), else `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<node>:latest`, which docker pulls. Cancel stops a container with SIGTERM and a 30 s grace before SIGKILL. Containers run without auto-remove, so the exit code is read even when a node fails at once; the container is removed after that.

That's it. The executor, canvas, and agent pick it up automatically.

## Key invariants

- **Nodes are pure functions**: inputs → outputs, no side channels between nodes
- **Nodes never read from each other directly**: only via R2 URIs passed as inputs
- **State is persisted at every node boundary**: a crash mid-workflow is resumable from the last completed node
- **The control plane never trains**: all ML work happens inside GPU pods
- **A node can be tested locally** with MinIO (fake R2) and manually set env vars
