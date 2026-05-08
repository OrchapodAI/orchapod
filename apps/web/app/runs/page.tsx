"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Play, Clock, DollarSign, Cpu } from "lucide-react";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.runs.list().then(setRuns).finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-8 py-6 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Runs</h1>
          <p className="text-sm text-slate-500 mt-0.5">{runs.length} total</p>
        </div>
      </div>

      <div className="flex-1 overflow-auto px-8 py-5">
        {loading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-16 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Play className="w-10 h-10 text-slate-700 mb-4" />
            <p className="text-slate-400 font-medium">No runs yet</p>
            <p className="text-slate-600 text-sm mt-1">
              Open a workflow and click{" "}
              <span className="text-violet-400">Run</span> to start training.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <Link
                key={run.id}
                href={`/runs/${run.id}`}
                className="flex items-center justify-between px-5 py-4 bg-slate-900 border border-slate-800 rounded-xl hover:border-violet-600/40 hover:bg-slate-800/60 transition-all"
              >
                <div className="flex items-center gap-4 min-w-0">
                  <div className="min-w-0">
                    <p className="text-sm font-mono text-slate-300 truncate">{run.id.slice(0, 12)}…</p>
                    <p className="text-xs text-slate-600 mt-0.5">
                      {new Date(run.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-6 shrink-0 text-xs text-slate-500">
                  {run.gpu_provider && (
                    <span className="flex items-center gap-1.5">
                      <Cpu className="w-3.5 h-3.5" />
                      {run.gpu_provider}
                    </span>
                  )}
                  {run.cost_usd != null && (
                    <span className="flex items-center gap-1">
                      <DollarSign className="w-3.5 h-3.5" />
                      {run.cost_usd.toFixed(3)}
                    </span>
                  )}
                  {run.started_at && (
                    <span className="flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5" />
                      {elapsed(run.started_at, run.finished_at)}
                    </span>
                  )}
                  <StatusBadge status={run.status} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function elapsed(start: string, end: string | null): string {
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
