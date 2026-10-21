"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, apiDate, cancelToken, explainError, toastError } from "@/lib/api";
import { applyRunEvent, canRetry, finished, type RunViewState } from "@/lib/runEvents";
import { useRunStream } from "@/lib/ws";
import { StatusBadge } from "@/components/StatusBadge";
import { LogStream, type LogLine } from "@/components/runs/LogStream";
import { LossChart } from "@/components/runs/LossChart";
import { NodeTimeline } from "@/components/runs/NodeTimeline";
import { ArtifactList } from "@/components/runs/ArtifactList";
import { EvalView } from "@/components/runs/EvalView";
import { DatasetCard } from "@/components/runs/DatasetCard";
import { ComparePlayground } from "@/components/runs/ComparePlayground";
import { datasetOf, evalOf, modelRefsOf } from "@/lib/results";

type Tab = "logs" | "chart" | "artifacts" | "eval" | "dataset" | "compare";

/** The live run view: /runs/[id], and embedded on /agent (where the back link opens the run page). */
export function RunView({ id, embedded = false }: { id: string; embedded?: boolean }) {
  const [view,         setView]         = useState<RunViewState | null>(null);
  const [activeNodeId, setActiveNodeId] = useState<string | undefined>();
  const [tab,          setTab]          = useState<Tab>("logs");
  const [cancelling,   setCancelling]   = useState(false);
  const [retrying,     setRetrying]     = useState<string | null>(null);
  const [attempt,      setAttempt]      = useState(0);   // bumped by a retry to reconnect the socket
  const [error,        setError]        = useState("");  // a failed retry (a failed cancel is a toast)
  const [loadError,    setLoadError]    = useState("");  // a failed snapshot

  const { events, connected } = useRunStream(id, attempt);

  // Snapshot = GET /runs/{id} + GET /runs/{id}/summary. Events have no replay, so the page snapshots on mount,
  // whenever the socket opens or closes (a retry's reconnect, the end of the run) and when an artifact lands.
  const loads = useRef(0);
  const shownResult = useRef(false);
  const load = useCallback(() => {
    const n = ++loads.current;
    Promise.all([api.runs.get(id), api.runs.summary(id)])
      .then(([run, summary]) => {
        if (n !== loads.current) return; // a newer snapshot is on its way
        setView({ run, summary });
        setLoadError("");
        // Once a run has succeeded, open its result (the eval, else the dataset); after that the tab is the user's.
        const result = evalOf(summary) ? "eval" : datasetOf(summary) ? "dataset" : null;
        if (summary.status === "succeeded" && result && !shownResult.current) {
          shownResult.current = true;
          setTab(result);
        }
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
      // The executor commits before it broadcasts, so a snapshot now also has what the page missed (NodeRun rows
      // created after it opened); an artifact brings the node's usd once its cost_json lands.
      if (event.type === "run_status" || event.type === "node_status" || event.type === "artifact") load();
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

  async function handleCancel() {
    setCancelling(true); setError("");
    try {
      const run = await api.runs.cancel(id);
      setView((v) => v && { ...v, run });
    } catch (err) {
      toastError("Couldn't cancel the run")(err); // a 403: this tab has no valid cancel token for the run
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
      load(); // a 409 (retried elsewhere, still stopping) means the node and button state are stale
    } finally {
      setRetrying(null);
    }
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
  const evalResult = evalOf(summary);
  const dataset = datasetOf(summary);
  const refs = modelRefsOf(summary);
  const stub = artifacts.some((a) => a.name === "metrics_json" && a.meta?.stub === true); // the SDK marks STUB=1 runs
  const tabs: Tab[] = ["logs", "chart", "artifacts", ...(evalResult ? ["eval" as const] : []),
    ...(dataset ? ["dataset" as const] : []), ...(refs.length >= 2 ? ["compare" as const] : [])];

  const canCancel = ["provisioning_gpu", "running"].includes(run.status);
  const starter = cancelToken(id) !== null; // read here, not in state: on /agent the id changes under one RunView

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
              run.started_at && `Started ${apiDate(run.started_at).toLocaleTimeString()}`].filter(Boolean).join("  ·  ")}
          </div>
        </div>
        <div className="spacer" />
        {(error || loadError) && <span role="alert" style={{ fontSize: 12, color: "var(--rose-ink)" }}>{error || loadError}</span>}
        <span className="pill mono tnum" title="Spent so far: Run.cost_usd, updated live by run_cost events">
          Cost ${(run.cost_usd ?? 0).toFixed(3)}
        </span>
        {canCancel && !starter && (
          <span id="cancel-note" className="muted" style={{ fontSize: 11.5 }}>Only the tab that started this run can cancel it</span>
        )}
        {canCancel && (
          <button
            onClick={handleCancel}
            disabled={cancelling || !starter}
            aria-describedby={starter ? undefined : "cancel-note"}
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
            {tabs.map((t) => (
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
                  <LossChart summary={summary} events={events} />
                </div>
              </div>
            )}

            {tab === "artifacts" && (
              <div className="card" style={{ padding: 16 }}>
                <ArtifactList artifacts={artifacts} done={finished(run.status)} />
              </div>
            )}

            {(tab === "eval" || tab === "dataset" || tab === "compare") && (
              <div style={{ height: "100%", overflow: "auto" }}>
                {tab === "eval" && evalResult && <EvalView {...evalResult} />}
                {tab === "dataset" && dataset && <DatasetCard {...dataset} />}
                {tab === "compare" && refs.length >= 2 && <ComparePlayground refs={refs} stub={stub} />}
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}
