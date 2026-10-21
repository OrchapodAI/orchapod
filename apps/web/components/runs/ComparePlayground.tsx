"use client";

import { useEffect, useRef, useState } from "react";
import { api, apiDate, explainError } from "@/lib/api";
import type { RunModelRef } from "@/lib/results";
import { applyCompareEvent, type CompareSide } from "@/lib/runEvents";
import { Callout } from "@/components/Callout";

/** One prompt to two of the run's models, streamed side by side through POST /compare; the server holds every key. */
export function ComparePlayground({ refs, stub }: { refs: RunModelRef[]; stub: boolean }) {
  const [pick, setPick] = useState([0, 1]);
  const [prompt, setPrompt] = useState("");
  const [sides, setSides] = useState<CompareSide[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []); // leaving the tab stops the stream

  async function compare(e: React.FormEvent) {
    e.preventDefault();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setSides([{ text: "", done: false, usd: null }, { text: "", done: false, usd: null }]);
    setError(""); setBusy(true);
    const [a, b] = pick.map((k) => {
      const { base_url, model, api_key_env, base_model } = refs[k]; // the four ModelRef keys, nothing else
      return { base_url, model, api_key_env, base_model };
    });
    try {
      await api.compare({ messages: [{ role: "user", content: prompt.trim() }], refs: [a, b], max_tokens: 512 },
        (ev) => setSides((ss) => applyCompareEvent(ss, ev)), ctrl.signal);
    } catch (err) {
      if (!ctrl.signal.aborted) setError(explainError(err));
    } finally {
      ctrl.abort(); // a malformed frame ends the read early: close the stream too
      setBusy(false);
    }
  }

  return (
    <div className="col" style={{ gap: 12 }}>
      <form onSubmit={compare} className="card col" style={{ padding: 16, gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {pick.map((k, side) => (
            <label key={side} className="col" style={{ gap: 4, fontSize: 12 }}>
              <span className="muted">Model {side ? "B" : "A"}</span>
              <select className="op-input op-input-sm" value={k} disabled={busy}
                onChange={(e) => { setPick((p) => p.map((v, i) => (i === side ? Number(e.target.value) : v))); setSides([]); }}>
                {refs.map((r, i) => <option key={i} value={i}>{r.label} · {r.model}</option>)}
              </select>
              {refs[k].expires_at && <Expiry at={refs[k].expires_at} />}
            </label>
          ))}
        </div>
        <textarea className="op-input" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
          placeholder="One prompt; both models answer it with the same settings." aria-label="Prompt"
          style={{ height: "auto", padding: "8px 10px", resize: "vertical", fontFamily: "var(--font-ui)" }} />
        <div className="row">
          {stub && <span className="pill warn" title="This run ran with STUB=1: placeholder outputs, no model calls">STUB</span>}
          <span className="muted" style={{ fontSize: 12 }}>Up to 512 tokens each. Keys stay on the server.</span>
          <div className="spacer" />
          {busy
            ? <button type="button" className="btn" onClick={() => abort.current?.abort()}>Stop</button>
            : <button type="submit" className="btn btn-primary" disabled={!prompt.trim()}>Compare</button>}
        </div>
      </form>

      {error && <div role="alert"><Callout tone="rose" title="Couldn't compare">{error}</Callout></div>}

      {sides.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {sides.map((s, i) => (
            <div key={i} className="card col" style={{ padding: 14, gap: 8 }} aria-busy={busy && !s.done}>
              <div className="row" style={{ minWidth: 0 }}>
                <b style={{ fontSize: 13 }}>{refs[pick[i]].label}</b>
                <span className="muted mono" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis" }}>{refs[pick[i]].model}</span>
              </div>
              <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 13, lineHeight: 1.6, minHeight: 60 }}>{s.text}</div>
              <div className="muted tnum" style={{ fontSize: 12 }}>
                {s.error ? <span style={{ color: "var(--rose-ink)" }}>{s.error}</span>
                  : s.done ? (s.usd == null ? "done" : `done · $${s.usd.toFixed(4)}`) : busy ? "streaming…" : "stopped before done"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// vllm-serve endpoints are deleted at expires_at; there is no extend.
function Expiry({ at }: { at: string }) {
  const t = apiDate(at);
  return (
    <span className="muted" style={{ fontSize: 11.5 }}>
      Endpoint {t.getTime() > Date.now() ? "expires" : "expired"} at {t.toLocaleTimeString()}
    </span>
  );
}
