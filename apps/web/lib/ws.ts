"use client";

import { useEffect, useState } from "react";
import type { WsEvent } from "./types";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8001";

/** Live run events. Bump `attempt` to reconnect: the server closes the socket after a terminal run_status (e.g. before a retry). */
export function useRunStream(runId: string, attempt = 0) {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/runs/${runId}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as WsEvent;
        setEvents((prev) => [...prev, event]);
      } catch {
        // ignore malformed frames
      }
    };

    return () => {
      ws.onopen = ws.onclose = ws.onerror = ws.onmessage = null; // the closing socket must not touch the next one's state
      ws.close();
      setConnected(false); // so the next socket's open is a change the page can re-sync on
    };
  }, [runId, attempt]);

  return { events, connected };
}
