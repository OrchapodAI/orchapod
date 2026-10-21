"use client";

import { useEffect, useRef, useState } from "react";
import type { WsEvent } from "./types";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8001";

export function useRunStream(runId: string) {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/runs/${runId}`);
    wsRef.current = ws;

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
      ws.close();
    };
  }, [runId]);

  return { events, connected };
}
