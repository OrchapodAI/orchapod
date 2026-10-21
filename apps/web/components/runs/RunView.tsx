"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, explainError } from "@/lib/api";
import { applyRunEvent, canRetry, type RunViewState } from "@/lib/runEvents";
import { useRunStream } from "@/lib/ws";
import { StatusBadge } from "@/components/StatusBadge";
import { LogStream, type LogLine } from "@/components/runs/LogStream";
import { LossChart, type ProgressPoint } from "@/components/runs/LossChart";
import { NodeTimeline } from "@/components/runs/NodeTimeline";
import { ArtifactList } from "@/components/runs/ArtifactList";
import { TryItChat } from "@/components/runs/TryItChat";
import { EndpointCountdown } from "@/components/runs/EndpointCountdown";

type Tab = "logs" | "chart" | "artifacts" | "endpoint";

/** The live run view: /runs/[id], and embedded on /agent (where the back link opens the run page). */
export function RunView({ id, embedded = false }: { id: string; embedded?: boolean }) {
  const [view,         setView]         = useState<RunViewState | null>(null);
  const [activeNodeId, setActiveNodeId] = useState<string | undefined>();
  const [tab,          setTab]          = useState<Tab>("logs");
  const [cancelling,   setCancelling]   = useState(false);
  const [retrying,     setRetrying]     = useState<string | null>(null);
  const [attempt,      setAttempt]      = useState(0);   // bumped by a retry to reconnect the socket
  const [error,        setError]        = useState("");  // a failed cancel or retry
  const [loadError,    setLoadError]    = useState("");  // a failed snapshot
  const [copied,       setCopied]       = useState(false);

  // Tracks the live expiry time — updated by WS endpoint_expiry events and Extend button
  const [expiresAt, setExpiresAt] = useState<string | null>(null);

  const { events, connected } = useRunStream(id, attempt);

  // Snapshot = GET /runs/{id} + GET /runs/{id}/summary. Events have no replay, so the page snapshots on mount,
  // whenever the socket opens or closes (a retry's reconnect, the end of the run) and when an artifact lands.
  const loads = useRef(0);
  const load = useCallback(() => {
    const n = ++loads.current;
    Promise.all([api.runs.get(id), api.runs.summary(id)])
      .then(([run, summary]) => {
        if (n !== loads.current) return; // a newer snapshot is on its way
        setView({ run, summary });
        setLoadError("");
        const ep = summary.artifacts.find((a) => a.kind === "endpoint");
        if (ep?.meta?.expires_at) setExpiresAt(String(ep.meta.expires_at));
      })
      .catch((err) => { if (n === loads.current) setLoadError(explainError(err)); });
  }, [id]);
  useEffect(load, [load, connected]);

  // Apply each event once: `events` only grows, across reconnects.
  const applied = useRef(0);
  useEffect(() => {
    for (const event of events.slice(applied.current)) {
      setView((v) => v && applyRunEvent(v, event));
      if (event.type === "node_status" && event.status === "running") setActiveNodeId(event.node_id);
      if (event.type === "artifact") {
        load(); // the new artifact, and the node's usd once its cost_json lands
        if (event.kind === "endpoint") setTab("endpoint"); // Endpoint is ready — jump to endpoint tab
      }
      if (event.type === "endpoint_expiry" && event.expires_at) setExpiresAt(event.expires_at);
    }
    applied.current = events.length;
  }, [events, load]);

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
    setCancelling(true); setError("");
    try {
      const run = await api.runs.cancel(id);
      setView((v) => v && { ...v, run });
    } catch (err) {
      setError(explainError(err));
    } finally {
      setCancelling(false);
    }
  }

  async function handleRetry(nodeId: string) {
    setRetrying(nodeId); setError("");
    try {
      const run = await api.runs.retry(id, nodeId);
      // The API reset the node to pending; the server closed the socket at the terminal status, so reconnect.
      setView((v) => v && applyRunEvent({ ...v, run }, { type: "node_status", node_id: nodeId, status: "pending" }));
      setAttempt((a) => a + 1);
    } catch (err) {
      setError(explainError(err));
    } finally {
      setRetrying(null);
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (!view) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", padding: 16 }}>
        {loadError
          ? <span role="alert" style={{ fontSize: 13, color: "var(--rose-ink)" }}>{loadError}</span>
          : <span className="muted">Loading…</span>}
      </div>
    );
  }
  const { run, summary } = view;
  const artifacts = summary.artifacts;

  // --- Endpoint data --------------------------------------------------------
  // The endpoint URL lives in artifact.uri (not meta.url — that was a bug).
  // The served model name is in the same node's model_ref (docs/contracts.md "vllm-serve").
  const endpointArtifact = artifacts.find((a) => a.kind === "endpoint");
  const endpointUrl      = endpointArtifact?.uri ?? null;
  const endpointApiKey   = endpointArtifact?.meta?.api_key
    ? String(endpointArtifact.meta.api_key)
    : null;
  const endpointModel = String(artifacts.find((a) =>
    a.node_id === endpointArtifact?.node_id && a.name === "model_ref")?.meta?.model ?? "model");

  const canCancel = ["provisioning_gpu", "running"].includes(run.status);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
      <div className="op-topbar" style={{ gap: 12 }}>
        {embedded
          ? <Link href={`/runs/${id}`} className="btn btn-sm btn-ghost" style={{ textDecoration: "none" }}>Open run page ↗</Link>
          : <Link href="/runs" className="btn btn-sm btn-ghost" style={{ textDecoration: "none" }}>← Runs</Link>}
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="mono" style={{ fontWeight: 500, fontSize: 13 }}>{id.slice(0, 8)}…</span>
            <StatusBadge status={run.status} />
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
            {[run.gpu_provider && `GPU: ${run.gpu_provider}`,
              run.started_at && `Started ${new Date(run.started_at).toLocaleTimeString()}`].filter(Boolean).join("  ·  ")}
          </div>
        </div>
        <div className="spacer" />
        {(error || loadError) && <span role="alert" style={{ fontSize: 12, color: "var(--rose-ink)" }}>{error || loadError}</span>}
        <span className="pill mono tnum" title="Spent so far: Run.cost_usd, updated live by run_cost events">
          Cost ${(run.cost_usd ?? 0).toFixed(3)}
        </span>
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
            {summary.nodes.length === 0 ? (
              <p className="muted" style={{ fontSize: 12, fontStyle: "italic", padding: "8px 0" }}>Waiting for nodes…</p>
            ) : (
              <NodeTimeline nodes={summary.nodes} activeNodeId={activeNodeId} onSelect={setActiveNodeId}
                canRetry={canRetry(run.status)} retrying={retrying} onRetry={handleRetry} />
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
