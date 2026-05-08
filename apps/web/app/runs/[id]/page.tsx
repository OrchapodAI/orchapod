"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, StopCircle, Loader2, AlertCircle, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import type { Run, NodeRun, Artifact } from "@/lib/types";
import { useRunStream } from "@/lib/ws";
import { StatusBadge } from "@/components/StatusBadge";
import { LogStream, type LogLine } from "@/components/runs/LogStream";
import { LossChart, type ProgressPoint } from "@/components/runs/LossChart";
import { NodeTimeline } from "@/components/runs/NodeTimeline";
import { ArtifactList } from "@/components/runs/ArtifactList";
import clsx from "clsx";

type Tab = "logs" | "chart" | "artifacts";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [run, setRun] = useState<Run | null>(null);
  const [nodeRuns, setNodeRuns] = useState<NodeRun[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | undefined>();
  const [tab, setTab] = useState<Tab>("logs");
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");

  const { events, connected } = useRunStream(id);

  // Initial load
  useEffect(() => {
    api.runs.get(id).then(setRun);
    api.runs.nodes(id).then(setNodeRuns);
    api.runs.artifacts(id).then(setArtifacts);
  }, [id]);

  // Apply incoming WebSocket events to local state
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
        // Re-fetch artifacts when one lands
        api.runs.artifacts(id).then(setArtifacts);
      }
    }
  }, [events, id]);

  // Derived: log lines from events
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

  // Derived: progress points for loss chart
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
  const isTerminal = run && ["succeeded", "failed", "cancelled"].includes(run.status);
  const canCancel = run && ["provisioning_gpu", "running"].includes(run.status);

  if (!run) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/60 shrink-0 gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/runs" className="p-1.5 rounded-md text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h1 className="text-sm font-semibold text-slate-100 font-mono truncate">
                {id.slice(0, 8)}…
              </h1>
              <StatusBadge status={run.status} />
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {run.gpu_provider ? `GPU: ${run.gpu_provider}` : ""}
              {run.cost_usd != null ? `  ·  $${run.cost_usd.toFixed(3)}` : ""}
              {run.started_at ? `  ·  Started ${new Date(run.started_at).toLocaleTimeString()}` : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {error && (
            <p className="flex items-center gap-1 text-xs text-red-400">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}
          {endpointArtifact && (
            <a
              href={String(endpointArtifact.meta?.url ?? "#")}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-emerald-900/40 text-emerald-300 border border-emerald-800 hover:bg-emerald-900/60 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Open endpoint
            </a>
          )}
          {canCancel && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-900/50 hover:bg-red-900/50 transition-colors"
            >
              {cancelling
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <StopCircle className="w-3.5 h-3.5" />}
              Cancel
            </button>
          )}
          <Link
            href={`/canvas/${run.workflow_id}`}
            className="px-3 py-1.5 rounded-lg text-sm text-slate-400 bg-slate-800 hover:bg-slate-700 transition-colors"
          >
            View workflow
          </Link>
        </div>
      </div>

      {/* Body: sidebar + main */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left sidebar: node timeline */}
        <div className="w-60 shrink-0 border-r border-slate-800 bg-slate-900/40 flex flex-col">
          <div className="px-4 py-3 border-b border-slate-800">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Nodes</p>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {nodeRuns.length === 0 ? (
              <p className="text-xs text-slate-700 italic">Waiting for nodes…</p>
            ) : (
              <NodeTimeline
                nodes={nodeRuns}
                activeNodeId={activeNodeId}
                onSelect={setActiveNodeId}
              />
            )}
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Tabs */}
          <div className="flex items-center gap-1 px-4 pt-3 pb-0 border-b border-slate-800 shrink-0">
            {(["logs", "chart", "artifacts"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={clsx(
                  "px-4 py-2 text-sm font-medium rounded-t-lg transition-colors capitalize -mb-px border-b-2",
                  tab === t
                    ? "text-violet-300 border-violet-500 bg-violet-900/10"
                    : "text-slate-500 border-transparent hover:text-slate-300"
                )}
              >
                {t}
                {t === "artifacts" && artifacts.length > 0 && (
                  <span className="ml-1.5 text-[10px] bg-violet-800/60 text-violet-300 px-1.5 py-0.5 rounded-full">
                    {artifacts.length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab panels */}
          <div className="flex-1 overflow-hidden p-4">
            {tab === "logs" && (
              <LogStream lines={logLines} activeNodeId={activeNodeId} connected={connected} />
            )}

            {tab === "chart" && (
              <div className="h-full bg-slate-950 rounded-xl border border-slate-800 flex flex-col overflow-hidden">
                <div className="px-4 py-2.5 border-b border-slate-800 shrink-0">
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Training Loss</p>
                </div>
                <div className="flex-1 p-4">
                  <LossChart data={progressPoints} />
                </div>
              </div>
            )}

            {tab === "artifacts" && (
              <div className="bg-slate-950 rounded-xl border border-slate-800 p-4">
                <ArtifactList artifacts={artifacts} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
