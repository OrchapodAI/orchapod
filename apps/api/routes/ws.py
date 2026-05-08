"""
apps/api/routes/ws.py

WebSocket endpoint for live run streaming.

  WS /ws/runs/{run_id}

The frontend connects here to receive real-time events:
  - {type: "run_status", status: "running" | "succeeded" | "failed" | "cancelled"}
  - {type: "node_status", node_id: "...", status: "running" | "succeeded" | "failed"}
  - {type: "log", node_id: "...", ts: "...", level: "INFO", message: "..."}
  - {type: "progress", node_id: "...", step: 42, total: 500, loss: 1.234}
  - {type: "artifact", node_id: "...", name: "lora_adapter", uri: "r2://..."}

Events are published to Redis by the executor and internal webhooks,
then forwarded here to all connected WebSocket clients for that run.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.services.events import event_bus

router = APIRouter()


@router.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: uuid.UUID):
    await websocket.accept()
    try:
        async for event in event_bus.subscribe(run_id):
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close(code=1011)
