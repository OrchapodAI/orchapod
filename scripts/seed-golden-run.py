"""Seed the golden run for the hosted app (`make demo`), or export a finished run as the new golden run.

    python scripts/seed-golden-run.py                  # into DATABASE_URL and ORCHAPOD_R2_*, read the way the API reads them
    python scripts/seed-golden-run.py --export RUN_ID  # a finished run and its small files → scripts/golden-run.json

The fixture holds what the app reads for one finished run: its workflow, run, node runs, artifacts, models and agent run
(with the cached report), plus the text files its artifacts point to (up to 1 MB each: datasets, eval_summary, metrics,
logs). So the run page, the eval view, the downloads and the report render without a single model call. Seeding replaces
that run if it is already there (same ids), keeps its timestamps (an old run never counts toward today's budget) and
moves its r2:// URIs to ORCHAPOD_R2_BUCKET. Directory artifacts (lora_adapter) and binaries (GGUF) are not copied:
their rows still show, their downloads do not.

The committed fixture is a STUB run of the real-estate template (every metric says "stub": true) until the real golden
run replaces it: TODO(D8) `--export` that run, commit the file, `make demo` on the hosted app.
TODO(D8): run `gitleaks detect --no-git --source scripts/golden-run.json` before committing an export: it copies the
objects' text verbatim (artifact meta is redacted, file contents are not).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps"), str(ROOT / "packages/sdk-py")]

from sqlalchemy import delete, select  # noqa: E402

from api import database  # noqa: E402
from api.models.db import AgentRun, Artifact, Model, NodeRun, Run, RunStatus, Workflow  # noqa: E402
from api.services import storage  # noqa: E402
from api.services.redact import redact  # noqa: E402

FIXTURE = ROOT / "scripts/golden-run.json"
MAX_BYTES = 1_000_000


async def export(run_id: uuid.UUID) -> dict:
    """The run's rows and its file artifacts' text, from the API's database and object store."""
    async with database.AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None or run.status not in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            raise SystemExit(f"run {run_id} is {'missing' if run is None else run.status.value}: export a finished run")
        nodes = (await db.scalars(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.started_at))).all()
        artifacts = (await db.scalars(select(Artifact).where(Artifact.node_run_id.in_([n.id for n in nodes]))
                                      .order_by(Artifact.created_at))).all()
        models = (await db.scalars(select(Model).where(Model.run_id == run_id))).all()
        workflow, agent_run = await db.get(Workflow, run.workflow_id), await db.get(AgentRun, run_id)
    fixture = {"bucket": storage._bucket(), "workflow": _dump(workflow), "run": _dump(run),
               "nodes": [_dump(n) for n in nodes], "artifacts": [{**_dump(a), "meta": redact(a.meta)} for a in artifacts],
               "models": [_dump(m) for m in models], "agent_run": _dump(agent_run), "objects": {}}
    s3 = storage._get_client()
    for a in artifacts:
        if not a.uri.startswith(f"r2://{storage._bucket()}/"):
            continue
        key = storage.r2_uri_to_key(a.uri)
        try:
            obj = s3.get_object(Bucket=storage._bucket(), Key=key)
        except s3.exceptions.NoSuchKey:
            continue  # a directory artifact: a key prefix, not an object
        if obj["ContentLength"] <= MAX_BYTES:
            try:
                fixture["objects"][key] = obj["Body"].read().decode()
            except UnicodeDecodeError:
                pass  # a binary
    return fixture


def _dump(row) -> dict | None:
    return None if row is None else row.model_dump(mode="json")


async def seed(fixture: dict) -> uuid.UUID:
    """Upload the fixture's files, then insert its rows, replacing the run if it is there; returns the run id."""
    f = json.loads(json.dumps(fixture).replace(f"r2://{fixture['bucket']}/", f"r2://{storage._bucket()}/"))
    storage.ensure_bucket_exists()
    s3 = storage._get_client()
    for key, text in f["objects"].items():
        s3.put_object(Bucket=storage._bucket(), Key=key, Body=text.encode())

    run_id = uuid.UUID(f["run"]["id"])
    await database.create_tables()
    async with database.AsyncSessionLocal() as db:
        nodes = select(NodeRun.id).where(NodeRun.run_id == run_id)
        for old in (delete(Model).where(Model.run_id == run_id), delete(Artifact).where(Artifact.node_run_id.in_(nodes)),
                    delete(AgentRun).where(AgentRun.run_id == run_id), delete(NodeRun).where(NodeRun.run_id == run_id),
                    delete(Run).where(Run.id == run_id)):
            await db.execute(old)
        for table, rows in ((Workflow, [f["workflow"]] if f["workflow"] else []), (Run, [f["run"]]), (NodeRun, f["nodes"]),
                            (Artifact, f["artifacts"]), (Model, f["models"]),
                            (AgentRun, [f["agent_run"]] if f["agent_run"] else [])):
            for row in rows:  # merge: the workflow may serve other runs too, so it is updated, never deleted
                await db.merge(table.model_validate(row))
            await db.flush()  # parents before children: the tables only know each other through foreign keys
        await db.commit()
    return run_id


async def _then_dispose(work):
    try:
        return await work
    finally:
        await database.engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--export", metavar="RUN_ID", type=uuid.UUID, help="write this finished run to the fixture instead")
    args = p.parse_args()
    if args.export:
        fixture = asyncio.run(_then_dispose(export(args.export)))
        FIXTURE.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
        print(f"run {args.export} → {FIXTURE}: {len(fixture['artifacts'])} artifacts, {len(fixture['objects'])} files")
    else:
        run_id = asyncio.run(_then_dispose(seed(json.loads(FIXTURE.read_text()))))
        print(f"golden run seeded: /runs/{run_id}, /agent/runs/{run_id}/report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
