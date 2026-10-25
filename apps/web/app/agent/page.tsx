"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, capNote, demoNote, explainError, usd } from "@/lib/api";
import type { AgentPlan, AgentReport, AgentTemplate, Run } from "@/lib/types";
import { reportNext, seenFinishedAt, splitReport } from "@/lib/runEvents";
import { planYaml } from "@/lib/workflowYaml";
import { NODE_META } from "@/components/canvas/OrchaNode";
import { StatusBadge } from "@/components/StatusBadge";
import { Callout } from "@/components/Callout";
import { RunView } from "@/components/runs/RunView";

const MAX_INTENT = 2000; // contracts: POST /agent/plan takes at most 2000 chars

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
  const [templates, setTemplates] = useState<AgentTemplate[] | null>(null);
  const [templatesError, setTemplatesError] = useState("");
  const [runs, setRuns] = useState<Run[]>([]); // which golden runs this API has to link to
  const planRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const runRef = useRef<HTMLDivElement>(null);

  // A new plan, error or run view renders below the five template cards, off screen at 1024×768 (qa-w10 F5): bring it into view.
  useEffect(() => { planRef.current?.scrollIntoView({ block: "nearest" }); }, [reply]);
  useEffect(() => { errorRef.current?.scrollIntoView({ block: "nearest" }); }, [error]);
  useEffect(() => { runRef.current?.scrollIntoView({ block: "nearest" }); }, [runId]);

  // The three canonical intents with ready plans (GET /agent/templates).
  useEffect(() => {
    api.agent.templates().then(setTemplates).catch((err) => setTemplatesError(explainError(err)));
  }, []);

  // A template above the cap links to its golden run only if this API has one (the newest 500 runs, as the runs page reads them): no list, no link.
  useEffect(() => {
    if (templates?.some((t) => t.fits === false)) api.runs.list(undefined, 500).then(setRuns).catch(() => {});
  }, [templates]);

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

  async function handleRun(text: string, plan: AgentPlan) {
    setBusy("run"); setError(null);
    try {
      setRunId((await api.agent.run(text, plan.plan)).run_id);
    } catch (err) {
      // A 422 carries the server's validation errors; like the plan's own, they keep Run disabled.
      const errors = (err as { body?: { errors?: string[] } }).body?.errors;
      if (errors?.length) setReply({ ...plan, errors });
      setError({ title: "Couldn't start the run", message: explainError(err) });
    } finally {
      setBusy("");
    }
  }

  // One-click Run: the template is the plan card, already planned (at reduced scale when the API offers it).
  // The intent box is left alone, so a typed draft survives.
  function runTemplate(t: AgentTemplate) {
    const { plan, estimate } = t.reduced ?? t;
    const reply: AgentPlan = { plan, rationale: t.rationale, estimate, warnings: [], errors: [] };
    setAsked(t.intent); setReply(reply); setRunId(null);
    handleRun(t.intent, reply);
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
          <p role="note" style={{
            padding: "8px 12px", borderRadius: 6, fontSize: 12.5, lineHeight: 1.5, fontWeight: 400,
            background: "var(--sky-soft)", border: "1px solid var(--sky)", color: "var(--sky-ink)",
          }}>
            <b>Demo mode.</b> {demoNote(templates, runs)}
          </p>

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
              <div className="spacer" />
              <span className="muted mono tnum" style={{ fontSize: 11 }}>{intent.length}/{MAX_INTENT}</span>
              <button type="submit" className="btn btn-primary" disabled={!intent.trim() || busy !== ""}>
                {busy === "plan" ? "Planning…" : "Plan"}
              </button>
            </div>
          </form>

          <section aria-label="Templates" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
            {templatesError ? <div style={{ gridColumn: "1 / -1" }}><Callout tone="amber" title="Templates unavailable">{templatesError}</Callout></div>
              : !templates ? <p className="muted" style={{ fontSize: 13 }}>Loading templates…</p>
              : templates.length === 0 ? (
                <p className="muted" style={{ fontSize: 13, gridColumn: "1 / -1" }}>
                  No templates are available yet. Describe what you want above and press Plan.
                </p>
              )
              : templates.map((t) => { const cap = capNote(t, runs); return (
                <div key={t.slug} className="card col" style={{ padding: 14, gap: 6 }}>
                  <span style={{ fontWeight: 600, fontSize: 13.5 }}>{t.title}</span>
                  <span className="dim" style={{ fontSize: 12.5, flex: 1 }}>{t.intent}</span>
                  <div className="row" style={{ marginTop: 4 }}>
                    <span className="mono tnum muted" style={{ fontSize: 12 }} title="Estimated cost and wall time">
                      {usd((t.reduced ?? t).estimate?.usd)} · {mins((t.reduced ?? t).estimate?.minutes)}
                    </span>
                    <div className="spacer" />
                    <button type="button" className="btn btn-sm btn-primary" onClick={() => runTemplate(t)}
                      disabled={busy !== "" || cap !== null} aria-label={`Run template: ${t.title}`}
                      aria-describedby={cap ? `cap-${t.slug}` : undefined}>▶ Run</button>
                  </div>
                  {cap && (
                    <p id={`cap-${t.slug}`} style={{ fontSize: 12, fontWeight: 400, color: "var(--amber-ink)" }}>
                      {cap.text}{cap.href && <>; <Link href={cap.href} style={{ color: "var(--brand)", textDecoration: "underline" }}>watch the golden run</Link></>}
                    </p>
                  )}
                </div>
              ); })}
          </section>

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
            <div ref={planRef} className="card" aria-label="Plan" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
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
                <button className="btn btn-primary" onClick={() => handleRun(asked, reply)}
                  disabled={reply.errors.length > 0 || busy !== "" || runId !== null}>
                  {busy === "run" ? "Starting…" : "▶ Run"}
                </button>
              </div>
            </div>
          )}

          {error && <div ref={errorRef} role="alert"><Callout tone="rose" title={error.title}>{error.message}</Callout></div>}

          {runId && (
            <>
              <div ref={runRef} className="card" style={{ height: 560, overflow: "hidden" }}>
                <RunView id={runId} embedded />
              </div>
              <ReportCard key={runId} runId={runId} />
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
  const [gone, setGone] = useState(false); // the run ended REPORT_WAIT_MS ago and its report never came

  // The one poll loop, every 5 s: until the report is ready (the API writes it in the background once the run ends), for at most
  // REPORT_WAIT_MS after the run ended (reportNext); a 404 means this run will never have one.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let endedAt: number | undefined; // when a poll first saw the run finished; forgotten when it runs again (Retry node)
    async function poll() {
      let ready = false;
      try {
        const r = await api.agent.report(runId);
        if (!live) return;
        setReport(r);
        setError("");
        ready = r.ready;
        endedAt = seenFinishedAt(r.status, endedAt, Date.now());
      } catch (err) {
        if (!live) return;
        setError(explainError(err));
        if ((err as { status?: number }).status === 404) return;
      }
      const next = reportNext(ready, endedAt, Date.now());
      if (next === "gone") setGone(true);
      else if (next === "wait") timer = setTimeout(poll, 5000);
    }
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, [runId]);

  const { title, body } = splitReport(report?.markdown ?? ""); // null until the report is ready

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
        <>
          {title && <h2 style={{ fontSize: 15, fontWeight: 600 }}>{title}</h2>}
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-ui)", fontSize: 13, lineHeight: 1.6, margin: 0 }}>
            {body}
          </pre>
        </>
      ) : gone ? (
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Report unavailable, <Link href={`/runs/${runId}`} style={{ color: "var(--brand)", textDecoration: "underline" }}>see the run page</Link>
        </p>
      ) : !error && (
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Nemotron writes the report when the run finishes; checking every 5 s.
        </p>
      )}
    </div>
  );
}
