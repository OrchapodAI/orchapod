"use client";

import { useEffect, useState, type ReactNode } from "react";
import { api, explainError } from "@/lib/api";
import type { EvalSummary, Verdict } from "@/lib/types";
import { Callout } from "@/components/Callout";

const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const ORDER = { tuned_first: "tuned shown first", base_first: "base shown first" } as const;
const PILL = { win: "succeeded", tie: "pending", loss: "failed" } as const;

/** judge-eval's result (docs/contracts.md "judge-eval"): win rate, W/T/L, consistency, exact match, then every judged row. */
export function EvalView({ stats, samplesUrl }: { stats: Omit<EvalSummary, "samples">; samplesUrl: string | null }) {
  const [samples, setSamples] = useState<Verdict[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!samplesUrl) return;
    let live = true;
    api.artifacts.content<EvalSummary>(samplesUrl)
      .then((s) => { if (live) setSamples(s.samples ?? []); })
      .catch((err) => {
        if (live) setError(err instanceof TypeError
          ? "The browser could not fetch eval_summary from object storage (network or CORS)." : explainError(err));
      });
    return () => { live = false; };
  }, [samplesUrl]);

  const { wins, ties, losses } = stats;
  const decided = wins + ties + losses; // errored rows are left out of the rate
  const bars = [["wins", wins, "var(--mint)"], ["ties", ties, "var(--ink-4)"], ["losses", losses, "var(--rose)"]] as const;

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card" style={{ padding: 16 }}>
        <div className="row" style={{ gap: 28, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <div className="muted" style={{ fontSize: 12 }}>Win rate, tuned vs base</div>
            <div className="tnum" style={{ fontSize: 40, fontWeight: 600, lineHeight: 1.1 }}>{pct(stats.win_rate)}</div>
            <div className="muted tnum" style={{ fontSize: 12 }}>(wins + ½ ties) ÷ {decided} verdicts</div>
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div role="img" aria-label={`${wins} wins, ${ties} ties, ${losses} losses`}
              style={{ display: "flex", height: 14, borderRadius: 4, overflow: "hidden", background: "var(--bg-3)", marginTop: 6 }}>
              {bars.map(([k, n, color]) => n > 0 && <div key={k} style={{ width: `${(n / decided) * 100}%`, background: color }} />)}
            </div>
            <div className="row tnum" style={{ gap: 14, fontSize: 12.5, marginTop: 8, flexWrap: "wrap" }}>
              {bars.map(([k, n, color]) => (
                <span key={k} className="row" style={{ gap: 5 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />{n} {k}
                </span>
              ))}
              {stats.errors > 0 && <span style={{ color: "var(--rose-ink)" }}>{stats.errors} errors (left out)</span>}
            </div>
            <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
              The judge sees both answer orders. A win needs tuned picked in both, a loss base in both; anything else is a tie.
            </p>
          </div>
        </div>
        <div className="row" style={{ gap: 24, marginTop: 14, fontSize: 13, flexWrap: "wrap" }}>
          <span>Consistency <b className="tnum">{pct(stats.consistency)}</b> <span className="muted">of rows get the same pick in both orders</span></span>
          {stats.exact_match && (
            <span>Exact match <b className="tnum">base {pct(stats.exact_match.base)} → tuned {pct(stats.exact_match.tuned)}</b></span>
          )}
        </div>
        <div className="muted mono" style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.7, wordBreak: "break-all" }}>
          base {stats.base?.model} · tuned {stats.tuned?.model}<br />
          judge {stats.judge_model} · temperature {stats.decoding?.temperature} · max {stats.decoding?.max_tokens} tokens ·
          {" "}{stats.judged} of {stats.n} rows judged{stats.stub ? " · STUB" : ""}
        </div>
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Judged samples</div>
        {error ? <Callout tone="rose" title="Couldn't load the judged samples">{error}</Callout>
          : !samplesUrl ? <p className="muted" style={{ fontSize: 13 }}>eval_summary has no download link.</p>
          : !samples ? <p className="muted" style={{ fontSize: 13 }}>Loading the judged samples…</p>
          : samples.length === 0 ? <p className="muted" style={{ fontSize: 13 }}>No samples in eval_summary.</p>
          : samples.map((v) => <Sample key={v.i} v={v} />)}
      </div>
    </div>
  );
}

function Text({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="muted" style={{ fontSize: 11.5, marginBottom: 3 }}>{title}</div>
      <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", background: "var(--bg-2)", border: "1px solid var(--line)",
                    borderRadius: 6, padding: "8px 10px", lineHeight: 1.55 }}>
        {children}
      </div>
    </div>
  );
}

const correct = (c: boolean | null) => (c == null ? "" : c ? " · exact match ✓" : " · exact match ✗");

// Questions, answers, context and URLs are model output or scraped web text: shown as text, linked only when http(s).
function Sample({ v }: { v: Verdict }) {
  const label = v.verdict ?? (v.error ? "error" : "not judged");
  return (
    <details style={{ borderTop: "1px solid var(--line)", padding: "8px 0" }}>
      <summary style={{ cursor: "pointer", fontSize: 13, lineHeight: 1.7 }}>
        <span className="muted mono tnum">#{v.i}</span>{" "}
        <span className={`pill ${v.verdict ? PILL[v.verdict] : v.error ? "warn" : "pending"}`}><span className="dot" />{label}</span>{" "}
        {v.question}
      </summary>
      <div className="col" style={{ gap: 10, padding: "10px 0 4px", fontSize: 13 }}>
        {v.error && <div style={{ color: "var(--rose-ink)" }}>{v.error}</div>}
        <Text title="Question">{v.question}</Text>
        <Text title="Reference">{v.reference}</Text>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Text title={`Base${correct(v.base_correct)}`}>{v.base}</Text>
          <Text title={`Tuned${correct(v.tuned_correct)}`}>{v.tuned}</Text>
        </div>
        {v.judgments?.map((j) => (
          <div key={j.order} style={{ lineHeight: 1.55 }}>
            <b>Judge, {ORDER[j.order] ?? j.order}:</b> picked {j.winner}. <span className="dim">{j.reasoning}</span>
          </div>
        ))}
        {v.context && (
          <details>
            <summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>
              Context{v.source_url && <> · {/^https?:\/\//.test(v.source_url)
                ? <a href={v.source_url} target="_blank" rel="noreferrer">{v.source_url}</a> : v.source_url}</>}
            </summary>
            <div style={{ marginTop: 6 }}><Text title="Passage the judge saw">{v.context}</Text></div>
          </details>
        )}
      </div>
    </details>
  );
}
