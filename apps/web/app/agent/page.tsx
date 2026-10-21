"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, explainError } from "@/lib/api";
import type { AgentPlan, AgentReport } from "@/lib/types";
import { planYaml } from "@/lib/workflowYaml";
import { NODE_META } from "@/components/canvas/OrchaNode";
import { StatusBadge } from "@/components/StatusBadge";
import { RunView } from "@/components/runs/RunView";

// The three canonical intents (docs/agent_knowledge.md).
const EXAMPLES = [
  "Fine-tune Llama 3B on US real-estate compliance: Fair Housing Act, RESPA, TILA/TRID, state licensing",
  "Generate synthetic data of movie likes, shares and subscribes",
  "Quantize a model which is an expert in maths",
];
const MAX_INTENT = 2000; // contracts: POST /agent/plan takes at most 2000 chars

const usd = (n: number | null | undefined) => (n == null ? "–" : `$${n.toFixed(2)}`);
const mins = (n: number | null | undefined) => (n == null ? "–" : `~${Math.round(n)} min`);

// Literal model ids in a node's inputs; refs resolve at run time, so they are skipped.
function modelsOf(inputs: Record<string, unknown> = {}): string[] {
  return Object.entries(inputs).flatMap(([k, v]) => {
    if (!k.includes("model")) return [];
    if (typeof v === "string") return v && !v.startsWith("${{") ? [v] : [];
    const model = (v as { model?: unknown } | null)?.model;
    return typeof model === "string" ? [model] : [];
  });
}

function Callout({ tone, title, children }: { tone: "amber" | "rose"; title: string; children: ReactNode }) {
  return (
    <div style={{
      background: `var(--${tone}-soft)`, border: `1px solid var(--${tone})`, borderRadius: 6,
      padding: "10px 14px", color: `var(--${tone}-ink)`, fontSize: 13, lineHeight: 1.5,
    }}>
      <div style={{ fontWeight: 600 }}>{title}</div>
      <div style={{ marginTop: 2 }}>{children}</div>
    </div>
  );
}

const list = (items: string[]) => (
  <ul style={{ margin: 0, paddingLeft: 18 }}>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
);

export default function AgentPage() {
  const router = useRouter();
  const [intent, setIntent] = useState("");
  const [asked, setAsked] = useState("");
  const [reply, setReply] = useState<AgentPlan | null>(null);
  const [error, setError] = useState<{ title: string; message: string } | null>(null);
  const [busy, setBusy] = useState<"" | "plan" | "edit" | "run">("");
  const [runId, setRunId] = useState<string | null>(null);

  async function handlePlan(e: React.FormEvent) {
    e.preventDefault();
    const text = intent.trim();
    if (!text || busy) return;
    setAsked(text); setReply(null); setRunId(null); setError(null); setBusy("plan");
    try {
      setReply(await api.agent.plan(text));
    } catch (err) {
      setError({ title: "The agent couldn't plan this", message: explainError(err) });
    } finally {
      setBusy("");
    }
  }

  async function handleEdit() {
    if (!reply) return;
    setBusy("edit"); setError(null);
    try {
      const wf = await api.workflows.create({ name: reply.plan.name || "agent-plan", yaml: planYaml(reply.plan) });
      router.push(`/canvas/${wf.id}`);
    } catch (err) {
      setError({ title: "Couldn't open the plan on the canvas", message: explainError(err) });
      setBusy("");
    }
  }

  async function handleRun() {
    if (!reply) return;
    setBusy("run"); setError(null);
    try {
      setRunId((await api.agent.run(asked, reply.plan)).run_id);
    } catch (err) {
      // A 422 carries the server's validation errors; like the plan's own, they keep Run disabled.
      const errors = (err as { body?: { errors?: string[] } }).body?.errors;
      if (errors?.length) setReply({ ...reply, errors });
      setError({ title: "Couldn't start the run", message: explainError(err) });
    } finally {
      setBusy("");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="op-topbar">
        <div className="op-crumbs"><span className="here">Orchapod Agent</span></div>
        <span className="muted" style={{ fontSize: 12 }}>Nemotron on Nebius Token Factory turns one sentence into a workflow</span>
        <div className="spacer" />
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "28px 24px" }}>
        <div style={{ maxWidth: 960, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
          <form onSubmit={handlePlan} className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <label htmlFor="intent" style={{ fontSize: 13, fontWeight: 500 }}>What should Orchapod build?</label>
            <textarea
              id="intent"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              onKeyDown={(e) => {
                // Enter that confirms an IME composition is not a send (Safari reports it as keyCode 229).
                if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return;
                e.preventDefault(); e.currentTarget.form?.requestSubmit();
              }}
              maxLength={MAX_INTENT}
              rows={3}
              placeholder="Describe the model or dataset you want. Enter sends, Shift+Enter adds a line."
              style={{
                width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid var(--line-2)",
                fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--ink-1)", resize: "vertical",
              }}
            />
            <div className="row" style={{ flexWrap: "wrap" }}>
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" className="btn btn-sm" onClick={() => setIntent(ex)}
                  style={{ whiteSpace: "normal", textAlign: "left", maxWidth: 300 }}>
                  {ex}
                </button>
              ))}
              <div className="spacer" />
              <span className="muted mono tnum" style={{ fontSize: 11 }}>{intent.length}/{MAX_INTENT}</span>
              <button type="submit" className="btn btn-primary" disabled={!intent.trim() || busy !== ""}>
                {busy === "plan" ? "Planning…" : "Plan"}
              </button>
            </div>
          </form>

          {asked && (
            <div style={{
              alignSelf: "flex-end", maxWidth: "80%", background: "var(--brand-soft)", color: "var(--brand-ink)",
              borderRadius: 8, padding: "10px 14px", fontSize: 13, whiteSpace: "pre-wrap",
            }}>
              {asked}
            </div>
          )}

          {/* Always rendered, so screen readers announce planning and the plan that arrives. */}
          <p role="status" className={busy === "plan" ? "muted" : "sr-only"} style={{ fontSize: 13 }}>
            {busy === "plan" ? "Nemotron is planning…"
              : reply ? `Plan ready: ${reply.plan.name}, ${reply.plan.nodes.length} nodes, ${reply.errors.length} errors.` : ""}
          </p>

          {reply && (
            <div className="card" aria-label="Plan" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="row">
                <span style={{ fontWeight: 600 }}>{reply.plan.name}</span>
                <span className="pill">{reply.plan.nodes.length} nodes</span>
                <div className="spacer" />
                <span className="mono tnum" style={{ fontSize: 13 }} title="Estimated cost and wall time">
                  {usd(reply.estimate?.usd)} · {mins(reply.estimate?.minutes)}
                </span>
              </div>
              {reply.rationale && <p className="dim" style={{ fontSize: 13, margin: 0 }}>{reply.rationale}</p>}
              <table className="tbl">
                <thead>
                  <tr><th>#</th><th>Node</th><th>Type</th><th>Models</th><th style={{ textAlign: "right" }}>Estimate</th></tr>
                </thead>
                <tbody>
                  {reply.plan.nodes.map((n, i) => {
                    const est = reply.estimate?.by_node?.[n.id];
                    return (
                      <tr key={n.id}>
                        <td className="muted tnum">{i + 1}</td>
                        <td className="mono" style={{ fontSize: 12 }}>{n.id}</td>
                        <td>{NODE_META[n.type]?.label ?? n.type} <span className="muted mono" style={{ fontSize: 11 }}>{n.type}</span></td>
                        <td className="mono" style={{ fontSize: 11.5, wordBreak: "break-all" }}>{modelsOf(n.inputs).join(", ") || "–"}</td>
                        <td className="mono tnum" style={{ textAlign: "right", fontSize: 12, whiteSpace: "nowrap" }}>
                          {est ? `${usd(est.usd)} · ${mins(est.minutes)}` : "–"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {reply.warnings.length > 0 && <Callout tone="amber" title="Warnings">{list(reply.warnings)}</Callout>}
              {reply.errors.length > 0 && <Callout tone="rose" title="Errors">{list(reply.errors)}</Callout>}
              <div className="row">
                {reply.errors.length > 0 && (
                  <span style={{ fontSize: 12, color: "var(--rose-ink)" }}>Run stays disabled until the plan has no errors.</span>
                )}
                <div className="spacer" />
                <button className="btn" onClick={handleEdit} disabled={busy !== ""}>
                  {busy === "edit" ? "Opening…" : "Edit on canvas"}
                </button>
                <button className="btn btn-primary" onClick={handleRun}
                  disabled={reply.errors.length > 0 || busy !== "" || runId !== null}>
                  {busy === "run" ? "Starting…" : "▶ Run"}
                </button>
              </div>
            </div>
          )}

          {error && <div role="alert"><Callout tone="rose" title={error.title}>{error.message}</Callout></div>}

          {runId && (
            <>
              <div className="card" style={{ height: 560, overflow: "hidden" }}>
                <RunView id={runId} embedded />
              </div>
              <ReportCard runId={runId} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ReportCard({ runId }: { runId: string }) {
  const [report, setReport] = useState<AgentReport | null>(null);
  const [error, setError] = useState("");

  // Poll every 5 s until the report is ready; a 404 means this run will never have one.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const r = await api.agent.report(runId);
        if (!live) return;
        setReport(r);
        setError("");
        if (r.ready) return;
      } catch (err) {
        if (!live) return;
        setError(explainError(err));
        if ((err as { status?: number }).status === 404) return;
      }
      timer = setTimeout(poll, 5000);
    }
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, [runId]);

  return (
    <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="row">
        <span style={{ fontWeight: 600 }}>Report</span>
        {report && <StatusBadge status={report.status} />}
        <div className="spacer" />
        {report && (
          <span className="mono tnum" style={{ fontSize: 12 }}>
            {usd(report.cost_usd)} spent of {usd(report.estimate?.usd)} estimated
          </span>
        )}
      </div>
      {error && <Callout tone="rose" title="Couldn't load the report">{error}</Callout>}
      {report?.error && <Callout tone="rose" title="Run failed">{report.error}</Callout>}
      {report?.ready && report.markdown ? (
        <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-ui)", fontSize: 13, lineHeight: 1.6, margin: 0 }}>
          {report.markdown}
        </pre>
      ) : !error && (
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Nemotron writes the report when the run finishes; checking every 5 s.
        </p>
      )}
    </div>
  );
}
