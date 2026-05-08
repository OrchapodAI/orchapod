"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Run, Workflow } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

const BAR_DAYS = 14;

function RunVolumeChart({ runs }: { runs: Run[] }) {
  // Build per-day counts for the last 14 days
  const now = Date.now();
  const days: { completed: number; failed: number }[] = Array.from({ length: BAR_DAYS }, () => ({ completed: 0, failed: 0 }));
  for (const r of runs) {
    const age = (now - new Date(r.created_at).getTime()) / 86400000;
    const idx = Math.floor(age);
    if (idx >= 0 && idx < BAR_DAYS) {
      const slot = days[BAR_DAYS - 1 - idx];
      if (r.status === "failed") slot.failed++;
      else slot.completed++;
    }
  }
  const maxH = Math.max(1, ...days.map(d => d.completed + d.failed));

  const completedCount = runs.filter(r => r.status === "succeeded").length;
  const failedCount = runs.filter(r => r.status === "failed").length;

  return (
    <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <div className="row" style={{ marginBottom: 10 }}>
        <div className="muted mono" style={{ fontSize: 11, letterSpacing: "0.06em" }}>RUN VOLUME · LAST 14 DAYS</div>
        <div className="spacer" />
        <span className="muted" style={{ fontSize: 11.5 }}>
          {completedCount} completed · {failedCount} failed
        </span>
      </div>
      <div className="row" style={{ gap: 3, alignItems: "flex-end", height: 52 }}>
        {days.map((d, i) => {
          const total = d.completed + d.failed;
          const h = total === 0 ? 3 : Math.max(4, Math.round((total / maxH) * 48));
          return (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 1, alignItems: "center" }}>
              {d.failed > 0 && (
                <div style={{ width: "100%", height: Math.round((d.failed / Math.max(1, total)) * h), background: "var(--rose)", borderRadius: "2px 2px 0 0" }} />
              )}
              <div style={{
                width: "100%", height: d.failed > 0 ? h - Math.round((d.failed / Math.max(1, total)) * h) : h,
                background: "var(--brand)", borderRadius: d.failed > 0 ? 0 : "2px 2px 0 0", opacity: 0.85,
                minHeight: 3,
              }} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.runs.list(), api.workflows.list()])
      .then(([rs, wfs]) => { setRuns(rs); setWorkflows(wfs); })
      .finally(() => setLoading(false));
  }, []);

  const wfMap = Object.fromEntries(workflows.map(w => [w.id, w]));

  const filtered = runs.filter(r => {
    const wfName = wfMap[r.workflow_id]?.name ?? "";
    const q = search.toLowerCase();
    return r.id.includes(q) || wfName.toLowerCase().includes(q);
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Topbar */}
      <div className="op-topbar">
        <div className="op-crumbs">
          <span>orbital-research</span>
          <span className="sep">/</span>
          <span className="here">Runs</span>
        </div>
        <div className="spacer" />
        <button className="btn btn-sm btn-ghost">↻ Refresh</button>
        <button className="btn btn-sm btn-ghost">Export CSV</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, padding: 24, overflow: "auto" }}>
        <div style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>Runs</h1>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>
            {runs.length} total · {runs.filter(r => r.status === "running").length} running · {runs.filter(r => r.status === "failed").length} failed in last 7d
          </div>
        </div>

        {/* Run volume chart */}
        {!loading && <RunVolumeChart runs={runs} />}

        {/* Filter row */}
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <div className="row" style={{
            gap: 6, color: "var(--ink-3)", border: "1px solid var(--line-2)",
            borderRadius: 6, padding: "5px 10px", fontSize: 12.5, width: 280,
            background: "var(--surface)",
          }}>
            <span style={{ fontSize: 13 }}>⌕</span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter by id, workflow, node…"
              style={{
                border: "none", outline: "none", background: "transparent",
                font: "inherit", color: "var(--ink-1)", width: "100%", fontSize: 12.5,
              }}
            />
          </div>
          <button className="btn btn-sm btn-ghost">All workflows</button>
          <button className="btn btn-sm btn-ghost">Status: all</button>
          <button className="btn btn-sm btn-ghost">Owner: anyone</button>
          <button className="btn btn-sm btn-ghost">Last 7 days</button>
          <div className="spacer" />
          <span className="muted" style={{ fontSize: 12 }}>
            {filtered.length === runs.length ? `${runs.length} runs` : `${filtered.length} of ${runs.length}`}
          </span>
        </div>

        {loading ? (
          <div className="card" style={{ overflow: "hidden" }}>
            {[...Array(5)].map((_, i) => (
              <div key={i} style={{ height: 52, borderBottom: "1px solid var(--line)", opacity: 0.5 + i * 0.1 }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "72px 0", textAlign: "center" }}>
            <div style={{ fontSize: 28, marginBottom: 12 }}>▶</div>
            <h3 style={{ fontWeight: 500 }}>{search ? "No runs match your filter" : "No runs yet"}</h3>
            <p className="muted" style={{ fontSize: 13.5, marginTop: 6 }}>
              Open a workflow and click <span style={{ color: "var(--brand)", fontWeight: 500 }}>Run</span> to start training.
            </p>
          </div>
        ) : (
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Workflow</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Cost</th>
                  <th>GPU</th>
                  <th>Owner</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => {
                  const wf = wfMap[run.workflow_id];
                  return (
                    <tr key={run.id}>
                      <td>
                        <Link href={`/runs/${run.id}`} style={{ textDecoration: "none" }}>
                          <div className="mono" style={{ fontWeight: 500, fontSize: 12.5, color: "var(--ink-1)" }}>
                            {run.id.slice(0, 8)}·{run.id.slice(-4)}
                          </div>
                          <div className="muted" style={{ fontSize: 11 }}>{timeAgo(run.created_at)}</div>
                        </Link>
                      </td>
                      <td>
                        <div style={{ fontSize: 13, color: "var(--ink-1)" }}>{wf?.name ?? <span className="muted mono" style={{ fontSize: 11 }}>{run.workflow_id.slice(0, 8)}…</span>}</div>
                        <div className="muted mono" style={{ fontSize: 11 }}>—</div>
                      </td>
                      <td><StatusBadge status={run.status} /></td>
                      <td className="mono">
                        {run.started_at ? elapsed(run.started_at, run.finished_at) : "—"}
                      </td>
                      <td className="mono">{run.cost_usd != null ? `$${run.cost_usd.toFixed(3)}` : "—"}</td>
                      <td className="mono muted" style={{ fontSize: 11.5 }}>{run.gpu_provider ?? "—"}</td>
                      <td><div className="avatar">EM</div></td>
                      <td>
                        <Link href={`/runs/${run.id}`} className="btn btn-icon btn-ghost" style={{ textDecoration: "none" }}>
                          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8">
                            <circle cx="7" cy="7" r="1"/><circle cx="2" cy="7" r="1"/><circle cx="12" cy="7" r="1"/>
                          </svg>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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

function timeAgo(dateStr: string): string {
  const ms = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}
