"""
apps/api/routes/internal.py

Internal webhook endpoints called by node containers via the orchapod SDK.
These are NOT exposed to the public internet — protected by a shared secret
or network policy in production.

Routes:
  POST /internal/log           — receive a structured log line from a container
  POST /internal/artifact      — receive artifact registration after R2 upload
  POST /internal/progress      — receive training progress (step, loss) for charts
  POST /internal/ttl           — register a Serverless Endpoint; it is deleted at its expiry

The node's exit code decides its status (executor); every call carries X-Orchapod-Secret.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
import secrets
import uuid
from asyncio import sleep
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api import config
from api.database import get_session, AsyncSessionLocal
from api.models.db import (
    Artifact, ArtifactKind,
    Model, ModelFormat,
    NodeRun, NodeStatus,
    Run,
)
from api.services import budget
from api.services.events import event_bus
from api.services.redact import redact

# endpoint_url artifact id (str) → the task that deletes its endpoint at expiry; asyncio keeps only weak references.
_ttl_tasks: dict[str, asyncio.Task] = {}
DELETE_RETRY_S = 300  # a failed delete is tried again: the endpoint bills until it is gone
# A Nebius resource id; it becomes a REST path segment, so /endpoints/../jobs/x could otherwise delete any job.
ENDPOINT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
STUB_URL = "http://stub.invalid"  # contracts: a STUB endpoint runs here, and nothing exists at Nebius
log = logging.getLogger("api.internal")

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# R2: /internal/* is never open. Unset (or blank) → a random secret for this process, which the
# executor passes to containers; set it explicitly when running more than one API worker.
INTERNAL_SECRET = config.env("ORCHAPOD_INTERNAL_SECRET") or secrets.token_urlsafe(32)


def _verify_secret(x_orchapod_secret: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_orchapod_secret.encode(), INTERNAL_SECRET.encode()):
        raise HTTPException(status_code=403, detail="Invalid internal secret")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class LogEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    ts: str
    level: str         # INFO | WARN | ERROR | PROGRESS
    message: str


class ArtifactEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    artifact: dict     # {name, uri, kind, metadata}


class ProgressEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    step: int
    total: int | None = None
    loss: float | None = None
    extra: dict = {}


class RegisterTTLRequest(BaseModel):
    run_id:         str
    node_id:        str
    action:         str          # "register_ttl"
    keep_alive_min: int = Field(ge=1, le=120)  # vllm-serve's bounds: no endpoint outlives 2 h of GPU time
    endpoint_url:   str
    endpoint_id:    str = Field(pattern=ENDPOINT_ID.pattern)  # the Serverless Endpoint deleted at expiry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/log", status_code=204, dependencies=[Depends(_verify_secret)])
async def receive_log(event: LogEvent, db: Session):
    """
    Receive a log line from a container and forward it to the WebSocket subscribers.
    Only the last ERROR line is stored (NodeRun.error): a failed node's error is "exit <code>: <that line>".
    """
    from fastapi import Response
    if event.level == "ERROR":
        node_run = await db.scalar(select(NodeRun).where(NodeRun.run_id == event.run_id, NodeRun.node_id == event.node_id))
        if node_run and node_run.status == NodeStatus.RUNNING:  # a late line must not replace "cancelled"
            node_run.error = event.message
            await db.commit()  # before the event, like every other announced change
    await event_bus.publish(event.run_id, {
        "type": "log",
        "node_id": event.node_id,
        "ts": event.ts,
        "level": event.level,
        "message": event.message,
    })
    return Response(status_code=204)


@router.post("/artifact", status_code=201, dependencies=[Depends(_verify_secret)])
async def receive_artifact(event: ArtifactEvent, db: Session):
    """
    Called by io.write_output() in the container SDK after uploading to R2.
    Registers the artifact in the DB, auto-registers Model if kind=model,
    and notifies WebSocket subscribers.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id == event.run_id,
            NodeRun.node_id == event.node_id,
        )
    )
    node_run = result.scalar_one_or_none()
    if not node_run:
        raise HTTPException(status_code=404, detail="NodeRun not found")

    art_data = event.artifact
    try:
        kind = ArtifactKind(art_data["kind"])
    except ValueError:
        raise HTTPException(422, f"Unknown artifact kind '{art_data['kind']}'. "
                            f"Valid: {[k.value for k in ArtifactKind]}")
    if kind == ArtifactKind.ENDPOINT:  # a forged live row could steer expiry and /compare's pair rule
        raise HTTPException(422, "endpoints are registered through /internal/ttl only")

    meta = redact(art_data.get("metadata") or {})  # R10: a token in it is never stored
    cost = art_data["name"] == "cost_json"
    async with budget.cost_lock if cost else contextlib.nullcontext():
        added = None
        if cost:  # what the node spent, reconciled with its attempt's earlier cost_json and the executor's bill
            meta, added = await _reconcile(db, node_run, meta)
            if meta is None:
                return {"ok": True, "duplicate": True}
        artifact = Artifact(
            node_run_id=node_run.id,
            name=art_data["name"],
            kind=kind,
            uri=art_data["uri"],
            size_bytes=art_data.get("size_bytes"),
            meta=meta,
        )
        db.add(artifact)

        # Merge URI into NodeRun.outputs so downstream nodes can reference it
        outputs = dict(node_run.outputs or {})
        outputs[art_data["name"]] = art_data["uri"]
        node_run.outputs = outputs
        db.add(node_run)

        await db.flush()

        # Auto-register a Model record for any model artifact
        if kind == ArtifactKind.MODEL:
            _auto_register_model(db, artifact, node_run, art_data.get("metadata", {}))

        cost_usd = None
        if added is not None:  # it rolls up into Run.cost_usd
            cost_usd = await db.scalar(
                update(Run).where(Run.id == event.run_id)
                .values(cost_usd=func.coalesce(Run.cost_usd, 0) + Decimal(str(added)))
                .returning(Run.cost_usd).execution_options(synchronize_session=False))
        await db.commit()  # before the events: subscribers re-read /runs/{id}/summary on them
    if cost_usd is not None:
        await event_bus.publish(event.run_id, {"type": "run_cost", "cost_usd": float(cost_usd)})

    await event_bus.publish(event.run_id, {
        "type": "artifact",
        "node_id": event.node_id,
        "name": art_data["name"],
        "uri": art_data["uri"],
        "kind": art_data["kind"],
    })
    return {"ok": True, "artifact_id": str(artifact.id)}


async def _reconcile(db: AsyncSession, node_run: NodeRun, meta: dict) -> tuple[dict | None, float]:
    """A node's cost_json against its attempt's earlier ones (contracts "Run state machine"): its meta with usd = what
    it adds to the run, so the summary agrees, and reported_usd = the node's own figure; None for a re-send of a seq
    already counted. A node's figure is never negative, and its meta cannot pose as the executor's bill. 422 for a
    figure that is not a finite amount within twice ORCHAPOD_MAX_RUN_USD: one huge report would block the whole day."""
    meta = {k: v for k, v in meta.items() if k not in ("billed_by", "wall_usd", "reported_usd")}
    try:
        reported = float(meta.get("usd") or 0)
    except (TypeError, ValueError):
        reported = math.nan
    attempt = meta.get("attempt") if isinstance(meta.get("attempt"), str) and meta["attempt"] else budget.attempt_of(node_run)
    earlier = await budget.attempt_costs(db, node_run.id, attempt)
    if not math.isfinite(reported) or budget.reported_cost(earlier + [{**meta, "reported_usd": max(0.0, reported)}]) \
            > 2 * budget.run_cap(1.0):
        log.warning("refused a cost_json of %r from run %s node %s", meta.get("usd"), node_run.run_id, node_run.node_id)
        raise HTTPException(422, "cost_json usd must be a finite amount, and an attempt's reports at most twice "
                                 "ORCHAPOD_MAX_RUN_USD")
    reported, seq = max(0.0, reported), meta.get("seq")
    if isinstance(seq, int) and any(m.get("seq") == seq and m.get("billed_by") != "executor"
                                    and float(m.get("reported_usd", m.get("usd", 0))) >= reported for m in earlier):
        return None, 0.0
    new = {**meta, "reported_usd": reported, "attempt": attempt}
    added = round(budget.attempt_cost(earlier + [new]) - budget.attempt_cost(earlier), 6)
    return {**new, "usd": added}, added


def _auto_register_model(
    db:       AsyncSession,
    artifact: Artifact,
    node_run: NodeRun,
    metadata: dict[str, Any],
) -> None:
    """Create a Model registry entry from a model artifact."""
    fmt_str    = metadata.get("format", "hf").lower()
    base_model = metadata.get("base_model") or (node_run.inputs or {}).get("model", "unknown")

    try:
        fmt = ModelFormat(fmt_str)
    except ValueError:
        fmt = ModelFormat.HF

    slug   = base_model.split("/")[-1].lower().replace(".", "-")
    suffix = metadata.get("precision") or (f"awq{metadata.get('bits','4')}" if fmt == ModelFormat.AWQ else "")
    name   = f"{slug}-{fmt.value}" + (f"-{suffix}" if suffix else "")

    model = Model(
        user_id=node_run.run_id,
        name=name,
        base_model=base_model,
        format=fmt,
        uri=artifact.uri,
        size_bytes=artifact.size_bytes,
        tags=[fmt.value, base_model],
        artifact_id=artifact.id,
        node_run_id=node_run.id,
        run_id=node_run.run_id,
    )
    db.add(model)


@router.post("/progress", dependencies=[Depends(_verify_secret)])
async def receive_progress(event: ProgressEvent):
    """
    Receive training progress (step/loss) and broadcast to WebSocket subscribers.
    Used by the run viewer to render live loss charts.
    """
    await event_bus.publish(event.run_id, {
        "type": "progress",
        "node_id": event.node_id,
        "step": event.step,
        "total": event.total,
        "loss": event.loss,
        **event.extra,
    })
    return {"ok": True}


@router.post("/ttl", status_code=202, dependencies=[Depends(_verify_secret)])
async def register_ttl(body: RegisterTTLRequest, db: Session):
    """
    Called by vllm-serve once its endpoint answers: records it (outputs.endpoint_url and an endpoint_url artifact, which
    /compare's pair rule reads) and deletes it keep_alive_min later.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id  == uuid.UUID(body.run_id),
            NodeRun.node_id == body.node_id,
        )
    )
    node_run = result.scalar_one_or_none()
    if node_run is None:
        raise HTTPException(404, f"NodeRun not found: run_id={body.run_id}, node_id={body.node_id}")
    url = await _nebius_url(body.endpoint_id)  # the URL /compare will send ORCHAPOD_ENDPOINT_TOKEN to: never the node's
    if url is None or url != body.endpoint_url:
        raise HTTPException(422, f"endpoint {body.endpoint_id} is not running at {body.endpoint_url}")

    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=body.keep_alive_min)

    # One endpoint, one live expiry, and a registration never extends it: any holder of the internal secret could
    # otherwise keep an endpoint billing forever. A sooner one takes over; else the earlier timer stands.
    earlier = [a for a in await db.scalars(select(Artifact).where(Artifact.kind == ArtifactKind.ENDPOINT))
               if _live(a.meta) and a.meta["endpoint_id"] == body.endpoint_id]
    first = min((_expiry(a.meta) for a in earlier), default=None)
    takes_over = first is None or expires_at < first
    superseded = earlier if takes_over else []
    for a in superseded:
        a.meta = {**a.meta, "superseded_at": now.isoformat()}
    expires_at = expires_at if takes_over else first

    outputs = dict(node_run.outputs or {})
    outputs["endpoint_url"] = url
    outputs["expires_at"]   = expires_at.isoformat()
    node_run.outputs = outputs
    db.add(node_run)

    artifact = Artifact(
        node_run_id=node_run.id,
        name="endpoint_url",
        kind=ArtifactKind.ENDPOINT,
        uri=url,
        meta={
            "keep_alive_min": body.keep_alive_min,
            "registered_at":  now.isoformat(),
            "expires_at":     expires_at.isoformat(),
            "endpoint_id":    body.endpoint_id,
            **({} if takes_over else {"superseded_at": now.isoformat()}),  # the earlier row stays the live one
        },
    )
    db.add(artifact)
    await db.commit()  # before the timers change (a failed commit leaves the live one) and before the event
    for a in superseded:
        if task := _ttl_tasks.pop(str(a.id), None):
            task.cancel()
    if takes_over:
        _arm(artifact, node_run.run_id)

    await event_bus.publish(uuid.UUID(body.run_id), {
        "type":       "artifact",
        "node_id":    body.node_id,
        "name":       "endpoint_url",
        "uri":        url,
        "kind":       "endpoint",
        "expires_at": expires_at.isoformat(),
    })
    return {"status": "ttl_registered", "keep_alive_min": body.keep_alive_min, "expires_at": expires_at.isoformat()}


async def _nebius_url(endpoint_id: str) -> str | None:
    """The URL Nebius reports for the endpoint (None until it runs); a STUB endpoint's, with no call. 502 when Nebius
    does not answer: the node then deletes its endpoint."""
    if endpoint_id.startswith("stub-"):
        return STUB_URL
    try:
        return (await asyncio.to_thread(_endpoints().get, endpoint_id))["url"]
    except Exception as e:
        log.warning("endpoint %s not confirmed by Nebius: %s", endpoint_id, e)
        raise HTTPException(502, f"Nebius did not confirm endpoint {endpoint_id}, so it is not registered")


def _expiry(meta: dict) -> datetime | None:
    """A row's expires_at as an aware datetime; None when it is missing or not one."""
    try:
        at = datetime.fromisoformat(meta["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return at if at.tzinfo else None


def _live(meta: dict | None) -> bool:
    """A registered endpoint, with a readable expiry, neither deleted nor superseded by a later registration."""
    meta = meta or {}
    return bool(meta.get("endpoint_id")) and _expiry(meta) is not None and not (meta.get("deleted_at")
                                                                                 or meta.get("superseded_at"))


def _arm(artifact: Artifact, run_id: uuid.UUID) -> None:
    """Start the expiry task of a registered endpoint; _ttl_tasks holds it until it ends. A stored endpoint_id that is
    not an id (it would walk the REST path) is never sent."""
    if not ENDPOINT_ID.fullmatch(artifact.meta["endpoint_id"]):
        log.error("endpoint_url %s: %r is not an endpoint id, so nothing deletes it", artifact.id, artifact.meta["endpoint_id"])
        return
    key = str(artifact.id)
    _ttl_tasks[key] = task = asyncio.create_task(_expire(artifact.id, artifact.meta["endpoint_id"],
                                                         _expiry(artifact.meta), run_id, artifact.node_run_id))
    task.add_done_callback(lambda t: _ttl_tasks.pop(key, None) if _ttl_tasks.get(key) is t else None)


async def resume_ttls() -> None:
    """At API start (R9): every registered endpoint not yet deleted gets its expiry task back (they live only in
    memory), so one whose expiry passed while the API was down is deleted now."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(Artifact, NodeRun.run_id).join(NodeRun, NodeRun.id == Artifact.node_run_id)
                                .where(Artifact.kind == ArtifactKind.ENDPOINT))
        for artifact, run_id in rows:
            try:  # a row it cannot read is skipped: it never stops the API from starting
                if _live(artifact.meta):
                    _arm(artifact, run_id)
            except Exception:
                log.exception("endpoint_url %s not re-armed", artifact.id)


def _endpoints():
    """NebiusServerless().endpoints (contracts "NebiusServerless"): delete(endpoint_id)."""
    from packages.providers.nebius import NebiusServerless
    return NebiusServerless().endpoints


async def _expire(artifact_id: uuid.UUID, endpoint_id: str, expires_at: datetime, run_id: uuid.UUID,
                  node_run_id: uuid.UUID) -> None:
    """10 minutes before expires_at, warn the run page and the alert email; at expires_at, delete the endpoint (a 404
    means it is gone already; a stub-* endpoint never existed) and record meta.deleted_at. It changes no run or node
    status: the node succeeded when it registered, and its run ends on its own."""
    if (left := (expires_at - datetime.now(timezone.utc)).total_seconds()) > 600:
        await sleep(left - 600)
        await _warn(run_id, node_run_id)
        left = 600
    await sleep(max(0.0, left))
    while not endpoint_id.startswith("stub-"):
        try:
            await asyncio.to_thread(_endpoints().delete, endpoint_id)
            break
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                break
            if status in (400, 401, 403):  # refused for good; 408, 409, 429, 499 and 5xx pass
                log.error("endpoint %s not deleted: %s; it bills until the next API start tries again, or the console", endpoint_id, e)
                return
            log.error("endpoint %s not deleted (it bills until it is); retrying in %s s: %s", endpoint_id, DELETE_RETRY_S, e)
            await sleep(DELETE_RETRY_S)
    async with AsyncSessionLocal() as db:
        if artifact := await db.get(Artifact, artifact_id):
            artifact.meta = {**artifact.meta, "deleted_at": datetime.now(timezone.utc).isoformat()}
            await db.commit()


async def _warn(run_id: uuid.UUID, node_run_id: uuid.UUID) -> None:
    """T-10 min: the run page's endpoint_expiry event and the alert email; neither may stop the delete."""
    try:
        await event_bus.publish(run_id, {"type": "endpoint_expiry", "node_run_id": str(node_run_id),
                                         "minutes_remaining": 10})
        from api.services.email import send_endpoint_expiry_warning
        async with AsyncSessionLocal() as db:
            node_run = await db.get(NodeRun, node_run_id)
            await send_endpoint_expiry_warning(run_id=str(run_id), model=str((node_run.inputs or {}).get("model", "unknown")),
                                               endpoint_url=str((node_run.outputs or {}).get("endpoint_url", "")),
                                               minutes_remaining=10)
    except Exception as e:
        log.warning("endpoint expiry warning failed: %s", e)
