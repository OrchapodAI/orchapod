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
| `ORCHAPOD_RESUME_CHECKPOINT_URI` | R2 URI of checkpoint to resume from (optional) |

## Artifact addressing

All artifacts are stored in R2 at:
```
runs/{run_id}/{node_id}/{artifact_name}
```

R2 URI format: `r2://orchapod-artifacts/runs/{run_id}/{node_id}/{artifact_name}`

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

## Adding a new node

1. Create `containers/{node-name}/Dockerfile`; the build context is the repo root, so it does `COPY packages/sdk-py/orchapod /app/orchapod` and `COPY containers/{node-name}/run.py /app/run.py` (enforced by `tests/containers/test_dockerfiles.py`)
2. Create `containers/{node-name}/run.py` (follow template above)
3. Add input/output schemas to `packages/workflow_schema/models.py`
4. Register in `NODE_REGISTRY` in the same file
5. Build and push: `bash scripts/build-and-push-containers.sh`

That's it. The executor, canvas, and agent pick it up automatically.

## Key invariants

- **Nodes are pure functions**: inputs → outputs, no side channels between nodes
- **Nodes never read from each other directly**: only via R2 URIs passed as inputs
- **State is persisted at every node boundary**: a crash mid-workflow is resumable from the last completed node
- **The control plane never trains**: all ML work happens inside GPU pods
- **A node can be tested locally** with MinIO (fake R2) and manually set env vars
