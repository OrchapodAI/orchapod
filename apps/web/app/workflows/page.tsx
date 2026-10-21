"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Workflow, Run } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const [wfs, rs] = await Promise.all([api.workflows.list(), api.runs.list()]);
      setWorkflows(wfs);
      setRuns(rs);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  // Build per-workflow run stats
  const runsByWorkflow = runs.reduce<Record<string, Run[]>>((acc, r) => {
    if (!acc[r.workflow_id]) acc[r.workflow_id] = [];
    acc[r.workflow_id].push(r);
    return acc;
  }, {});

  const filtered = workflows.filter((w) =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Topbar */}
      <div className="op-topbar">
        <div className="op-crumbs">
          <span className="here">Workflows</span>
        </div>
        <div className="spacer" />
        <Link href="/workflows/new" className="btn btn-ghost btn-sm" style={{ textDecoration: "none" }}>
          Blank canvas
        </Link>
        <Link href="/workflows/new" className="btn btn-primary btn-sm" style={{ textDecoration: "none" }}>
          ✦ From prompt
        </Link>
      </div>

      {/* Body */}
      <div style={{ flex: 1, padding: 24, overflow: "auto" }}>
        <div style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>Workflows</h1>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>
            {workflows.length} workflows · {runs.length} total runs · sourced from canvas + prompt
          </div>
        </div>

        {/* Filter row */}
        <div className="row" style={{ gap: 8, marginBottom: 16 }}>
          <div className="row" style={{
            gap: 6, color: "var(--ink-3)", border: "1px solid var(--line-2)",
            borderRadius: 6, padding: "5px 10px", fontSize: 12.5, width: 280,
            background: "var(--surface)",
          }}>
            <span style={{ fontSize: 13 }}>⌕</span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by name, tag, node…"
              style={{
                border: "none", outline: "none", background: "transparent",
                font: "inherit", color: "var(--ink-1)", width: "100%", fontSize: 12.5,
              }}
            />
          </div>
          <button className="btn btn-sm btn-ghost">Owner: anyone</button>
          <button className="btn btn-sm btn-ghost">Tag: all</button>
          <button className="btn btn-sm btn-ghost">Status: all</button>
          <div className="spacer" />
          <div className="row" style={{ gap: 0, border: "1px solid var(--line-2)", borderRadius: 6, overflow: "hidden" }}>
            <button className="btn btn-sm btn-ghost" style={{ borderRadius: 0, background: "var(--brand-soft)", color: "var(--brand-ink)" }}>List</button>
            <button className="btn btn-sm btn-ghost" style={{ borderRadius: 0 }}>Cards</button>
          </div>
        </div>

        {loading ? (
          <div className="card" style={{ overflow: "hidden" }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{ height: 52, borderBottom: "1px solid var(--line)", opacity: 0.5 + i * 0.12 }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "96px 0", textAlign: "center" }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>✦</div>
            <h3 style={{ fontWeight: 500 }}>{search ? "No workflows match your search" : "No workflows yet"}</h3>
            <p className="muted" style={{ fontSize: 13.5, marginTop: 6, maxWidth: 300 }}>
              {search ? "Try a different search term." : "Create your first workflow from a prompt or blank canvas."}
            </p>
            {!search && (
              <Link href="/workflows/new" className="btn btn-primary" style={{ textDecoration: "none", marginTop: 20 }}>
                ✦ Create workflow
              </Link>
            )}
          </div>
        ) : (
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Name</th>
                  <th>Nodes</th>
                  <th>Last run</th>
                  <th>Status</th>
                  <th>Runs</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((w) => {
                  const wRuns = runsByWorkflow[w.id] ?? [];
                  const latestRun = wRuns.sort((a, b) =>
                    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                  )[0];
                  const nodeCount = w.graph_json?.nodes?.length ?? 0;
                  return (
                    <tr key={w.id}>
                      <td>
                        <div className="row" style={{ gap: 8 }}>
                          <span style={{ color: "var(--ink-3)", flexShrink: 0 }}>
                            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                              <circle cx="3" cy="7" r="1.5" fill="currentColor"/>
                              <circle cx="11" cy="3" r="1.5" fill="currentColor"/>
                              <circle cx="11" cy="11" r="1.5" fill="currentColor"/>
                              <line x1="4.5" y1="6.5" x2="9.5" y2="3.5" stroke="currentColor" strokeWidth="1"/>
                              <line x1="4.5" y1="7.5" x2="9.5" y2="10.5" stroke="currentColor" strokeWidth="1"/>
                            </svg>
                          </span>
                          <Link href={`/canvas/${w.id}`} style={{ textDecoration: "none" }}>
                            <div style={{ fontWeight: 500, color: "var(--ink-1)" }}>{w.name}</div>
                            <div className="mono muted" style={{ fontSize: 11 }}>{w.id.slice(0, 12)}</div>
                          </Link>
                        </div>
                      </td>
                      <td className="mono">{nodeCount > 0 ? nodeCount : "—"}</td>
                      <td className="muted">{latestRun ? timeAgo(latestRun.created_at) : "—"}</td>
                      <td>
                        {latestRun ? <StatusBadge status={latestRun.status} /> : <span className="muted" style={{ fontSize: 12 }}>—</span>}
                      </td>
                      <td className="mono">{wRuns.length > 0 ? wRuns.length : "—"}</td>
                      <td>
                        <div className="row" style={{ gap: 4 }}>
                          <Link href={`/canvas/${w.id}`} className="btn btn-icon btn-ghost" style={{ textDecoration: "none" }}>
                            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8">
                              <circle cx="7" cy="7" r="1"/><circle cx="2" cy="7" r="1"/><circle cx="12" cy="7" r="1"/>
                            </svg>
                          </Link>
                        </div>
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
