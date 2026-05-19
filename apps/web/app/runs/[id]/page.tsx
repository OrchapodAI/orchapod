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
import { TryItChat } from "@/components/runs/TryItChat";
import { EndpointCountdown } from "@/components/runs/EndpointCountdown";

type Tab = "logs" | "chart" | "artifacts" | "endpoint";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();

  const [run,          setRun]          = useState<Run | null>(null);
  const [nodeRuns,     setNodeRuns]     = useState<NodeRun[]>([]);
  const [artifacts,    setArtifacts]    = useState<Artifact[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | undefined>();
  const [tab,          setTab]          = useState<Tab>("logs");
  const [cancelling,   setCancelling]   = useState(false);
  const [error,        setError]        = useState("");
  const [copied,       setCopied]       = useState(false);

  // Tracks the live expiry time — updated by WS endpoint_expiry events and Extend button
  const [expiresAt, setExpiresAt] = useState<string | null>(null);

  const { events, connected } = useRunStream(id);

  useEffect(() => {
    api.runs.get(id).then(setRun);
    api.runs.nodes(id).then(setNodeRuns);
    api.runs.artifacts(id).then((arts) => {
      setArtifacts(arts);
      // Seed initial expiresAt from the endpoint artifact meta
      const ep = arts.find((a) => a.kind === "endpoint");
      if (ep?.meta?.expires_at) setExpiresAt(String(ep.meta.expires_at));
    });
  }, [id]);

  useEffect(() => {
    for (const event of events) {
      if (event.type === "run_status") {
        setRun((prev) => prev ? { ...prev, status: event.status } : prev);
      }
      if (event.type === "run_cost") {
        setRun((prev) => prev ? { ...prev, cost_usd: event.cost_usd } : prev);
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
        // Refresh artifact list; also update expiresAt if the new artifact has it
        api.runs.artifacts(id).then((arts) => {
          setArtifacts(arts);
          const ep = arts.find((a) => a.kind === "endpoint");
          if (ep?.meta?.expires_at) setExpiresAt(String(ep.meta.expires_at));
        });
        // Endpoint is ready — jump to endpoint tab
        if (event.kind === "endpoint") setTab("endpoint");
      }
      if (event.type === "endpoint_expiry" && event.expires_at) {
        setExpiresAt(event.expires_at);
      }
    }
  }, [events, id]);

  const logLines = useMemo<LogLine[]>(() => {
    return events
      .filter((e) => e.type === "log")
      .map((e) => ({
        ts:      (e as { ts: string }).ts,
        level:   (e as { level: string }).level,
        node_id: (e as { node_id: string }).node_id,
        message: (e as { message: string }).message,
      }));
  }, [events]);

  const progressPoints = useMemo<ProgressPoint[]>(() => {
    return events
      .filter((e) => e.type === "progress" && (e as { loss?: number }).loss != null)
      .map((e) => ({
        step:    (e as { step: number }).step,
        loss:    (e as { loss: number }).loss,
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

  // --- Endpoint data --------------------------------------------------------
  // The endpoint URL lives in artifact.uri (not meta.url — that was a bug).
  // Model comes from the vllm-serve node's inputs.
  const endpointArtifact = artifacts.find((a) => a.kind === "endpoint");
  const endpointUrl      = endpointArtifact?.uri ?? null;
  const endpointApiKey   = endpointArtifact?.meta?.api_key
    ? String(endpointArtifact.meta.api_key)
    : null;

  const vllmNode    = nodeRuns.find((n) => n.node_type === "vllm-serve");
  const endpointModel = vllmNode
    ? String((vllmNode.inputs as Record<string, unknown>)?.model ?? "model")
    : "model";

  const canCancel = run && ["provisioning_gpu", "running"].includes(run.status);

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (!run) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
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
        {endpointUrl && (
          <a
            href={endpointUrl.replace(/\/v1\/?$/, "")}
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
        {run.workflow_id && (
          <Link href={`/canvas/${run.workflow_id}`} className="btn btn-sm" style={{ textDecoration: "none" }}>
            View workflow
          </Link>
        )}
      </div>

      {/* Body */}
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

        {/* Main */}
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
            {endpointUrl && (
              <button
                onClick={() => setTab("endpoint")}
                style={{
                  padding: "10px 8px", border: "none", background: "transparent",
                  borderBottom: tab === "endpoint" ? "2px solid var(--mint)" : "2px solid transparent",
                  color: tab === "endpoint" ? "var(--mint-ink)" : "var(--ink-3)",
                  fontWeight: tab === "endpoint" ? 500 : 400, cursor: "pointer",
                  fontFamily: "var(--font-ui)", fontSize: 13,
                  display: "flex", alignItems: "center", gap: 6,
                }}
              >
                ⚡ Endpoint
              </button>
            )}
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

            {tab === "endpoint" && endpointUrl && (
              <div style={{ display: "flex", flexDirection: "column", gap: 16, height: "100%", overflow: "auto" }}>

                {/* Countdown + extend (KAN-30) */}
                {expiresAt && (
                  <EndpointCountdown
                    runId={id}
                    expiresAt={expiresAt}
                    onExtended={setExpiresAt}
                  />
                )}

                {/* URL card */}
                <div className="card" style={{ padding: 16, flexShrink: 0 }}>
                  <div className="muted mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
                    OpenAI-Compatible Endpoint
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 6, padding: "8px 12px" }}>
                    <span className="mono" style={{ flex: 1, fontSize: 12.5, wordBreak: "break-all", color: "var(--ink-1)" }}>
                      {endpointUrl}
                    </span>
                    <button onClick={() => copyToClipboard(endpointUrl)} className="btn btn-sm" style={{ flexShrink: 0 }}>
                      {copied ? "Copied!" : "Copy"}
                    </button>
                    <a
                      href={endpointUrl.replace(/\/v1\/?$/, "")}
                      target="_blank" rel="noreferrer"
                      className="btn btn-sm"
                      style={{ textDecoration: "none", flexShrink: 0, color: "var(--mint-ink)", background: "var(--mint-soft)", borderColor: "var(--mint)" }}
                    >
                      Open ↗
                    </a>
                  </div>
                  {endpointApiKey && (
                    <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="muted" style={{ fontSize: 12 }}>API key:</span>
                      <span className="mono" style={{ fontSize: 12, color: "var(--ink-2)" }}>
                        {endpointApiKey.slice(0, 20)}•••
                      </span>
                      <button onClick={() => copyToClipboard(endpointApiKey)} className="btn btn-sm">
                        Copy key
                      </button>
                    </div>
                  )}
                </div>

                {/* Try it chat (KAN-29) */}
                <div style={{ flex: 1, minHeight: 420 }}>
                  <TryItChat
                    endpointUrl={endpointUrl}
                    apiKey={endpointApiKey}
                    model={endpointModel}
                    costUsd={run.cost_usd ?? null}
                  />
                </div>

                {/* OpenAI snippet */}
                <div className="card" style={{ padding: 16, flexShrink: 0 }}>
                  <div className="muted mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
                    Usage (Python · OpenAI SDK)
                  </div>
                  <pre style={{
                    background: "oklch(0.13 0.02 260)", color: "oklch(0.90 0.02 260)",
                    borderRadius: 6, padding: "14px 16px", fontSize: 12.5, lineHeight: 1.7,
                    overflowX: "auto", margin: 0,
                  }}>{`from openai import OpenAI

client = OpenAI(
    base_url="${endpointUrl}",
    api_key="${endpointApiKey ?? "YOUR_API_KEY"}",
)

response = client.chat.completions.create(
    model="${endpointModel}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)`}
                  </pre>
                  <button
                    onClick={() => copyToClipboard(
`from openai import OpenAI

client = OpenAI(
    base_url="${endpointUrl}",
    api_key="${endpointApiKey ?? "YOUR_API_KEY"}",
)

response = client.chat.completions.create(
    model="${endpointModel}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)`
                    )}
                    className="btn btn-sm"
                    style={{ marginTop: 10 }}
                  >
                    Copy snippet
                  </button>
                </div>

              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}
