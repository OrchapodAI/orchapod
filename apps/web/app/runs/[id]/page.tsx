"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Run, NodeRun, Artifact } from "@/lib/types";
import { useRunStream } from "@/lib/ws";
import { StatusBadge } from "@/components/StatusBadge";
import { LogStream, type LogLine } from "@/components/runs/LogStream";
import { LossChart, type ProgressPoint } from "@/components/runs/LossChart";
import { NodeTimeline } from "@/components/runs/NodeTimeline";
import { ArtifactList } from "@/components/runs/ArtifactList";

type Tab = "logs" | "chart" | "artifacts";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();

  const [run, setRun] = useState<Run | null>(null);
  const [nodeRuns, setNodeRuns] = useState<NodeRun[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | undefined>();
  const [tab, setTab] = useState<Tab>("logs");
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");

  const { events, connected } = useRunStream(id);

  useEffect(() => {
    api.runs.get(id).then(setRun);
    api.runs.nodes(id).then(setNodeRuns);
    api.runs.artifacts(id).then(setArtifacts);
  }, [id]);

  useEffect(() => {
    for (const event of events) {
      if (event.type === "run_status") {
        setRun((prev) => prev ? { ...prev, status: event.status } : prev);
      }
      if (event.type === "node_status") {
        setNodeRuns((prev) =>
          prev.map((n) =>
            n.node_id === event.node_id ? { ...n, status: event.status } : n
          )
        );
        if (event.status === "running") setActiveNodeId(event.node_id);
      }
      if (event.type === "artifact") {
        api.runs.artifacts(id).then(setArtifacts);
      }
    }
  }, [events, id]);

  const logLines = useMemo<LogLine[]>(() => {
    return events
      .filter((e) => e.type === "log")
      .map((e) => ({
        ts: (e as { ts: string }).ts,
        level: (e as { level: string }).level,
        node_id: (e as { node_id: string }).node_id,
        message: (e as { message: string }).message,
      }));
  }, [events]);

  const progressPoints = useMemo<ProgressPoint[]>(() => {
    return events
      .filter((e) => e.type === "progress" && (e as { loss?: number }).loss != null)
      .map((e) => ({
        step: (e as { step: number }).step,
        loss: (e as { loss: number }).loss,
        node_id: (e as { node_id: string }).node_id,
      }));
  }, [events]);

  async function handleCancel() {
    setCancelling(true);
    try {
      const updated = await api.runs.cancel(id);
      setRun(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setCancelling(false);
    }
  }

  const endpointArtifact = artifacts.find((a) => a.kind === "endpoint");
  const canCancel = run && ["provisioning_gpu", "running"].includes(run.status);

  if (!run) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header / topbar */}
      <div className="op-topbar" style={{ gap: 12 }}>
        <Link href="/runs" className="btn btn-sm btn-ghost" style={{ textDecoration: "none" }}>← Runs</Link>
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="mono" style={{ fontWeight: 500, fontSize: 13 }}>{id.slice(0, 8)}…</span>
            <StatusBadge status={run.status} />
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
            {run.gpu_provider ? `GPU: ${run.gpu_provider}` : ""}
            {run.cost_usd != null ? `  ·  $${run.cost_usd.toFixed(3)}` : ""}
            {run.started_at ? `  ·  Started ${new Date(run.started_at).toLocaleTimeString()}` : ""}
          </div>
        </div>
        <div className="spacer" />
        {error && <span className="muted" style={{ fontSize: 12, color: "var(--rose)" }}>{error}</span>}
        {endpointArtifact && (
          <a
            href={String(endpointArtifact.meta?.url ?? "#")}
            target="_blank"
            rel="noreferrer"
            className="btn btn-sm"
            style={{ textDecoration: "none", color: "var(--mint-ink)", background: "var(--mint-soft)", borderColor: "var(--mint)" }}
          >
            Open endpoint ↗
          </a>
        )}
        {canCancel && (
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="btn btn-sm"
            style={{ color: "var(--rose-ink)", background: "var(--rose-soft)", borderColor: "var(--rose)" }}
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        )}
        <Link
          href={`/canvas/${run.workflow_id}`}
          className="btn btn-sm"
          style={{ textDecoration: "none" }}
        >
          View workflow
        </Link>
      </div>

      {/* Body: sidebar + main */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* Left: node timeline */}
        <div style={{ width: 220, flexShrink: 0, borderRight: "1px solid var(--line)", background: "var(--surface)", display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-2)" }}>
            <span className="muted mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase" }}>Nodes</span>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
            {nodeRuns.length === 0 ? (
              <p className="muted" style={{ fontSize: 12, fontStyle: "italic", padding: "8px 0" }}>Waiting for nodes…</p>
            ) : (
              <NodeTimeline nodes={nodeRuns} activeNodeId={activeNodeId} onSelect={setActiveNodeId} />
            )}
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
          {/* Tabs */}
          <div className="row" style={{ padding: "0 16px", borderBottom: "1px solid var(--line)", gap: 4, fontSize: 13, background: "var(--surface)", flexShrink: 0 }}>
            {(["logs", "chart", "artifacts"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  padding: "10px 8px", border: "none", background: "transparent",
                  borderBottom: tab === t ? "2px solid var(--brand)" : "2px solid transparent",
                  color: tab === t ? "var(--brand-ink)" : "var(--ink-3)",
                  fontWeight: tab === t ? 500 : 400, cursor: "pointer",
                  fontFamily: "var(--font-ui)", fontSize: 13, textTransform: "capitalize",
                  display: "flex", alignItems: "center", gap: 6,
                }}
              >
                {t}
                {t === "artifacts" && artifacts.length > 0 && (
                  <span className="pill" style={{ height: 16, fontSize: 10, padding: "0 5px" }}>{artifacts.length}</span>
                )}
              </button>
            ))}
            <div className="spacer" />
            <span className="muted" style={{ fontSize: 11.5 }}>
              {connected ? "● live" : "○ disconnected"}
            </span>
          </div>

          {/* Tab panels */}
          <div style={{ flex: 1, overflow: "hidden", padding: 16, background: "var(--bg-2)" }}>
            {tab === "logs" && (
              <LogStream lines={logLines} activeNodeId={activeNodeId} connected={connected} />
            )}
            {tab === "chart" && (
              <div className="card" style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-2)", flexShrink: 0 }}>
                  <span className="muted mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase" }}>Training Loss</span>
                </div>
                <div style={{ flex: 1, padding: 16 }}>
                  <LossChart data={progressPoints} />
                </div>
              </div>
            )}
            {tab === "artifacts" && (
              <div className="card" style={{ padding: 16 }}>
                <ArtifactList artifacts={artifacts} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
