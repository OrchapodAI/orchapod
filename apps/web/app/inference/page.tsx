"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BaseModel, InferenceEndpoint, InferenceMode } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

// ── Mode card ─────────────────────────────────────────────────────────────────

function ModeCard({
  id, title, description, icon, selected, onClick,
}: {
  id: InferenceMode;
  title: string;
  description: string;
  icon: React.ReactNode;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        textAlign: "left",
        padding: "14px 16px",
        borderRadius: "var(--r-3)",
        border: selected
          ? "1.5px solid var(--brand)"
          : "1.5px solid var(--line-2)",
        background: selected ? "var(--brand-soft)" : "var(--surface)",
        cursor: "pointer",
        transition: "border-color 0.1s, background 0.1s",
      }}
    >
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <span style={{ color: selected ? "var(--brand)" : "var(--ink-3)", fontSize: 16 }}>{icon}</span>
        <span style={{
          fontWeight: 600, fontSize: 13,
          color: selected ? "var(--brand-ink)" : "var(--ink-1)",
        }}>{title}</span>
      </div>
      <div style={{ fontSize: 12, color: selected ? "var(--brand-ink)" : "var(--ink-3)", lineHeight: 1.4 }}>
        {description}
      </div>
    </button>
  );
}

// ── Field ─────────────────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div className="row" style={{ gap: 6 }}>
        <label style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink-2)" }}>{label}</label>
        {hint && <span style={{ fontSize: 11.5, color: "var(--ink-4)" }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px",
  border: "1px solid var(--line-2)", borderRadius: "var(--r-2)",
  background: "var(--surface)", color: "var(--ink-1)",
  font: "inherit", fontSize: 13.5, outline: "none",
};

// ── Main page ─────────────────────────────────────────────────────────────────

export default function InferencePage() {
  const router = useRouter();
  const [models, setModels] = useState<BaseModel[]>([]);
  const [endpoints, setEndpoints] = useState<InferenceEndpoint[]>([]);
  const [loadingEndpoints, setLoadingEndpoints] = useState(true);

  // Form state
  const [mode, setMode] = useState<InferenceMode>("serve");
  const [model, setModel] = useState("");
  const [gpu, setGpu] = useState("1xH100");
  const [maxModelLen, setMaxModelLen] = useState(8192);
  const [keepAliveMin, setKeepAliveMin] = useState(60);
  const [precision, setPrecision] = useState<"q4_k_m" | "q5_k_m" | "q8_0">("q4_k_m");
  const [servedModelName, setServedModelName] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.registry.models().then(r => setModels(r.models));
    api.inference.endpoints()
      .then(setEndpoints)
      .finally(() => setLoadingEndpoints(false));
  }, []);

  async function handleDeploy(e: React.FormEvent) {
    e.preventDefault();
    if (!model.trim()) { setError("Model ID is required"); return; }
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.inference.deploy({
        model: model.trim(),
        mode,
        gpu,
        max_model_len: maxModelLen,
        keep_alive_min: keepAliveMin,
        precision,
        served_model_name: servedModelName || undefined,
        hf_token: hfToken || undefined,
      });
      router.push(`/runs/${res.run_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Deploy failed");
      setSubmitting(false);
    }
  }

  const needsServe   = mode === "serve" || mode === "quantize-serve";
  const needsQuantize = mode === "quantize-serve" || mode === "quantize-gguf";
  const activeCount  = endpoints.filter(e => e.status === "running" || e.status === "succeeded").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>

      {/* Topbar */}
      <div className="op-topbar">
        <div className="op-crumbs">
          <span className="here">Inference</span>
        </div>
        <div className="spacer" />
        <button className="btn btn-sm btn-ghost" onClick={() => {
          setLoadingEndpoints(true);
          api.inference.endpoints().then(setEndpoints).finally(() => setLoadingEndpoints(false));
        }}>↻ Refresh</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, padding: 24, overflow: "auto", display: "flex", flexDirection: "column", gap: 24 }}>

        {/* Header */}
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>Data Inference</h1>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>
            Deploy any HuggingFace model as an OpenAI-compatible endpoint, or quantize it for offline use.
          </div>
        </div>

        {/* Two-column layout: form + side info */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20, alignItems: "start" }}>

          {/* Deploy form */}
          <form onSubmit={handleDeploy} style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>

              {/* Mode selector */}
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink-2)", marginBottom: 8 }}>Deployment mode</div>
                <div className="row" style={{ gap: 10, alignItems: "stretch" }}>
                  <ModeCard
                    id="serve"
                    title="Serve"
                    icon="▶"
                    description="Direct vLLM endpoint. Fastest path — model loaded straight from HuggingFace."
                    selected={mode === "serve"}
                    onClick={() => setMode("serve")}
                  />
                  <ModeCard
                    id="quantize-serve"
                    title="Quantize → Serve"
                    icon="⚡"
                    description="AWQ-quantize first (4-bit), then serve. Lower VRAM, minimal quality loss."
                    selected={mode === "quantize-serve"}
                    onClick={() => setMode("quantize-serve")}
                  />
                  <ModeCard
                    id="quantize-gguf"
                    title="Quantize GGUF"
                    icon="📦"
                    description="Convert to GGUF for Ollama / llama.cpp. No serving — download and use locally."
                    selected={mode === "quantize-gguf"}
                    onClick={() => setMode("quantize-gguf")}
                  />
                </div>
              </div>

              {/* Model field */}
              <Field label="Model" hint="HuggingFace ID or R2 URI">
                <div style={{ position: "relative" }}>
                  <input
                    value={model}
                    onChange={e => setModel(e.target.value)}
                    placeholder="e.g. nvidia/Nemotron-Mini-4B-Instruct"
                    style={inputStyle}
                    list="model-suggestions"
                    autoComplete="off"
                  />
                  <datalist id="model-suggestions">
                    {models.map(m => <option key={m.id} value={m.id} label={m.name} />)}
                  </datalist>
                </div>

                {/* Quick-pick chips — Nemotron first */}
                <div className="row" style={{ gap: 5, flexWrap: "wrap", marginTop: 6 }}>
                  {/* Nemotron chips */}
                  {models.filter(m => m.family === "Nemotron").map(m => (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setModel(m.id)}
                      style={{
                        padding: "2px 9px", borderRadius: 999,
                        border: `1px solid ${model === m.id ? "var(--brand)" : "#76b900"}`,
                        background: model === m.id ? "var(--brand-soft)" : "#f0f9e8",
                        color: model === m.id ? "var(--brand-ink)" : "#3a6600",
                        fontSize: 11.5, cursor: "pointer", fontWeight: 500,
                      }}
                    >
                      ⚡ {m.name}
                    </button>
                  ))}
                  {/* Other models */}
                  {models.filter(m => m.family !== "Nemotron").slice(0, 4).map(m => (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setModel(m.id)}
                      style={{
                        padding: "2px 9px", borderRadius: 999,
                        border: "1px solid var(--line-2)",
                        background: model === m.id ? "var(--brand-soft)" : "transparent",
                        color: model === m.id ? "var(--brand-ink)" : "var(--ink-3)",
                        fontSize: 11.5, cursor: "pointer",
                      }}
                    >
                      {m.name}
                    </button>
                  ))}
                </div>
              </Field>

              {/* GPU */}
              <Field label="GPU" hint="Nebius AI Cloud preferred">
                <select value={gpu} onChange={e => setGpu(e.target.value)} style={{ ...inputStyle, appearance: "none" }}>
                  <option value="1xH100">1× H100 SXM — Nebius eu-north1 (~$2.49/hr)</option>
                  <option value="1xA100">1× A100 80GB — Nebius eu-north1 (~$1.89/hr)</option>
                  <option value="1xRTX4090">1× RTX 4090 — Vast.ai fallback (~$0.55/hr)</option>
                </select>
              </Field>

              {/* GGUF precision — only for quantize-gguf */}
              {mode === "quantize-gguf" && (
                <Field label="GGUF Precision">
                  <select value={precision} onChange={e => setPrecision(e.target.value as typeof precision)} style={{ ...inputStyle, appearance: "none" }}>
                    <option value="q4_k_m">Q4_K_M — good balance (recommended)</option>
                    <option value="q5_k_m">Q5_K_M — higher quality, larger file</option>
                    <option value="q8_0">Q8_0 — near-lossless, large file</option>
                  </select>
                </Field>
              )}

              {/* Serve settings — only when serving */}
              {needsServe && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  <Field label="Max context length" hint="tokens">
                    <input
                      type="number"
                      value={maxModelLen}
                      onChange={e => setMaxModelLen(Number(e.target.value))}
                      min={512} max={131072} step={512}
                      style={inputStyle}
                    />
                  </Field>
                  <Field label="Keep alive" hint="minutes">
                    <input
                      type="number"
                      value={keepAliveMin}
                      onChange={e => setKeepAliveMin(Number(e.target.value))}
                      min={5} max={1440} step={5}
                      style={inputStyle}
                    />
                  </Field>
                </div>
              )}

              {/* Advanced toggle */}
              <div>
                <button
                  type="button"
                  onClick={() => setShowAdvanced(v => !v)}
                  style={{
                    background: "none", border: "none", padding: 0,
                    color: "var(--ink-3)", fontSize: 12.5, cursor: "pointer",
                    display: "flex", alignItems: "center", gap: 5,
                  }}
                >
                  <span style={{ transform: showAdvanced ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block", transition: "transform 0.15s" }}>▶</span>
                  Advanced options
                </button>

                {showAdvanced && (
                  <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
                    {needsServe && (
                      <Field label="Served model name" hint="overrides /v1/models response">
                        <input
                          value={servedModelName}
                          onChange={e => setServedModelName(e.target.value)}
                          placeholder="my-model"
                          style={inputStyle}
                        />
                      </Field>
                    )}
                    <Field label="HuggingFace token" hint="for gated / private models">
                      <input
                        type="password"
                        value={hfToken}
                        onChange={e => setHfToken(e.target.value)}
                        placeholder="hf_…"
                        style={inputStyle}
                        autoComplete="off"
                      />
                    </Field>
                  </div>
                )}
              </div>

              {/* Error */}
              {error && (
                <div style={{
                  padding: "10px 14px", borderRadius: "var(--r-2)",
                  background: "var(--rose-soft)", color: "var(--rose-ink)",
                  fontSize: 13,
                }}>
                  {error}
                </div>
              )}

              {/* Submit */}
              <button
                type="submit"
                disabled={submitting || !model.trim()}
                className="btn btn-primary"
                style={{ width: "100%", justifyContent: "center", opacity: submitting || !model.trim() ? 0.55 : 1 }}
              >
                {submitting
                  ? "Deploying…"
                  : mode === "serve"
                    ? "▶ Deploy endpoint"
                    : mode === "quantize-serve"
                      ? "⚡ Quantize + Deploy"
                      : "📦 Quantize to GGUF"}
              </button>

            </div>
          </form>

          {/* Right: info panel */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

            {/* How it works */}
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)", letterSpacing: "0.05em", marginBottom: 10 }}>HOW IT WORKS</div>
              <ol style={{ margin: 0, padding: "0 0 0 16px", fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.7 }}>
                <li>A GPU pod is provisioned on Vast.ai</li>
                {needsQuantize && <li>Model is quantized inside the container</li>}
                {needsServe && <li>vLLM loads and serves the model</li>}
                {needsServe && <li>OpenAI-compatible endpoint is registered</li>}
                {needsServe && <li>Pod auto-terminates after keep-alive expires</li>}
                {!needsServe && <li>GGUF file is uploaded to R2 storage</li>}
              </ol>
            </div>

            {/* Endpoint usage */}
            {needsServe && (
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)", letterSpacing: "0.05em", marginBottom: 10 }}>ENDPOINT USAGE</div>
                <div style={{ fontSize: 12, color: "var(--ink-3)", marginBottom: 8, lineHeight: 1.5 }}>
                  Once running, use it exactly like OpenAI:
                </div>
                <pre style={{
                  background: "var(--code-bg)", color: "var(--code-text)",
                  borderRadius: "var(--r-2)", padding: "10px 12px",
                  fontSize: 11, lineHeight: 1.6, overflowX: "auto",
                  margin: 0,
                }}>{`from openai import OpenAI

client = OpenAI(
  base_url="<endpoint_url>/v1",
  api_key="orchapod",
)
r = client.chat.completions.create(
  model="${servedModelName || model || "your-model"}",
  messages=[{"role":"user",
             "content":"Hello!"}],
)
print(r.choices[0].message.content)`}</pre>
              </div>
            )}

            {/* Estimated time */}
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)", letterSpacing: "0.05em", marginBottom: 10 }}>ESTIMATED TIME</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {[
                  { label: "GPU provisioning", time: "1–3 min" },
                  ...(needsQuantize ? [{ label: "Quantization (AWQ/GGUF)", time: "5–20 min" }] : []),
                  ...(needsServe ? [{ label: "Model load + warmup", time: "1–3 min" }] : []),
                ].map(({ label, time }) => (
                  <div key={label} className="row" style={{ fontSize: 12.5 }}>
                    <span style={{ color: "var(--ink-3)" }}>{label}</span>
                    <div className="spacer" />
                    <span className="mono" style={{ color: "var(--ink-2)", fontSize: 12 }}>{time}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Active endpoints table */}
        <div>
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 500 }}>Active Endpoints</h2>
            <span className="muted" style={{ fontSize: 13, marginLeft: 8 }}>{activeCount} live</span>
          </div>

          {loadingEndpoints ? (
            <div className="card" style={{ overflow: "hidden" }}>
              {[...Array(2)].map((_, i) => (
                <div key={i} style={{ height: 50, borderBottom: "1px solid var(--line)", opacity: 0.5 + i * 0.25 }} />
              ))}
            </div>
          ) : endpoints.length === 0 ? (
            <div className="card" style={{ padding: "40px 24px", textAlign: "center" }}>
              <div style={{ fontSize: 24, marginBottom: 10 }}>▶</div>
              <div style={{ fontWeight: 500, marginBottom: 4 }}>No endpoints yet</div>
              <div className="muted" style={{ fontSize: 13 }}>Deploy a model above to create your first endpoint.</div>
            </div>
          ) : (
            <div className="card" style={{ overflow: "hidden" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Workflow</th>
                    <th>Status</th>
                    <th>Endpoint URL</th>
                    <th>GPU</th>
                    <th>Started</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {endpoints.map(ep => (
                    <tr key={ep.run_id}>
                      <td>
                        <div style={{ fontWeight: 500, fontSize: 13 }}>
                          {ep.model.split("/").pop()}
                        </div>
                        <div className="mono muted" style={{ fontSize: 11 }}>
                          {ep.model.includes("/") ? ep.model.split("/")[0] : ""}
                        </div>
                      </td>
                      <td>
                        <div style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{ep.workflow_name}</div>
                      </td>
                      <td>
                        <StatusBadge status={ep.status as Parameters<typeof StatusBadge>[0]["status"]} />
                      </td>
                      <td>
                        {ep.endpoint_url ? (
                          <a
                            href={ep.endpoint_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mono"
                            style={{ fontSize: 11.5, color: "var(--brand)", textDecoration: "none" }}
                          >
                            {ep.endpoint_url.replace(/^https?:\/\//, "")}
                          </a>
                        ) : (
                          <span className="muted" style={{ fontSize: 12 }}>provisioning…</span>
                        )}
                      </td>
                      <td className="mono muted" style={{ fontSize: 12 }}>{ep.gpu_provider ?? "—"}</td>
                      <td className="muted" style={{ fontSize: 12 }}>
                        {ep.started_at ? timeAgo(ep.started_at) : "—"}
                      </td>
                      <td>
                        <Link
                          href={`/runs/${ep.run_id}`}
                          className="btn btn-sm btn-ghost"
                          style={{ textDecoration: "none", fontSize: 12 }}
                        >
                          Logs →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

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
  return d === 1 ? "yesterday" : `${d}d ago`;
}
