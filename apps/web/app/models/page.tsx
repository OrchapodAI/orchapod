"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, explainError, toastError } from "@/lib/api";
import type { RegisteredModel } from "@/lib/types";

const FORMAT_LABEL: Record<string, string> = {
  hf:   "HF",
  awq:  "AWQ",
  gguf: "GGUF",
};

const FORMAT_COLOR: Record<string, { bg: string; text: string }> = {
  hf:   { bg: "var(--brand-soft)",  text: "var(--brand-ink)"  },
  awq:  { bg: "var(--mint-soft)",   text: "var(--mint-ink)"   },
  gguf: { bg: "#fff7ed",            text: "#9a3412"            },
};

export default function ModelsPage() {
  const [models,     setModels]     = useState<RegisteredModel[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [search,     setSearch]     = useState("");
  const [fmtFilter,  setFmtFilter]  = useState<string>("all");
  const [copied,     setCopied]     = useState<string | null>(null);
  const [error,      setError]      = useState("");

  useEffect(() => {
    api.models.list()
      .then(setModels)
      .catch((err) => { setError(explainError(err)); toastError("Couldn't load models")(err); })
      .finally(() => setLoading(false));
  }, []);

  function copyUri(uri: string) {
    navigator.clipboard.writeText(uri).then(() => {
      setCopied(uri);
      setTimeout(() => setCopied(null), 2000);
    }).catch(toastError("Couldn't copy the URI"));
  }

  const filtered = models.filter((m) => {
    const matchSearch = !search || [m.name, m.base_model, ...m.tags]
      .some((s) => s.toLowerCase().includes(search.toLowerCase()));
    const matchFmt = fmtFilter === "all" || m.format === fmtFilter;
    return matchSearch && matchFmt;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="op-topbar">
        <div className="op-crumbs"><span>Models</span></div>
        <div className="spacer" />
        <span className="muted" style={{ fontSize: 12 }}>{models.length} registered</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>

        {/* Filters */}
        <div className="row" style={{ gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
          <input
            type="search"
            placeholder="Search by name, base model, tag…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1, minWidth: 220, padding: "7px 10px", fontSize: 13,
              border: "1px solid var(--line)", borderRadius: 6,
              background: "var(--bg-2)", color: "var(--ink-1)", outline: "none",
            }}
          />
          {["all", "hf", "awq", "gguf"].map((f) => (
            <button
              key={f}
              onClick={() => setFmtFilter(f)}
              className="btn btn-sm"
              style={{
                fontWeight: fmtFilter === f ? 600 : 400,
                background:  fmtFilter === f ? "var(--brand-soft)"  : undefined,
                color:       fmtFilter === f ? "var(--brand-ink)"   : undefined,
                borderColor: fmtFilter === f ? "var(--brand)"       : undefined,
              }}
            >
              {f === "all" ? "All formats" : FORMAT_LABEL[f]}
            </button>
          ))}
        </div>

        {/* States */}
        {loading && <p className="muted" style={{ fontSize: 13 }}>Loading…</p>}

        {!loading && models.length === 0 && (
          <div style={{ textAlign: "center", marginTop: 64 }}>
            <p style={{ fontSize: 15, fontWeight: 500 }}>{error ? "Couldn't load models" : "No models registered yet"}</p>
            <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {error || "Models are auto-registered when a workflow run produces a model artifact (via the quantize, unsloth-train, or hf-download node)."}
            </p>
          </div>
        )}

        {!loading && models.length > 0 && filtered.length === 0 && (
          <p className="muted" style={{ fontSize: 13 }}>No models match your filters.</p>
        )}

        {/* Model list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((m) => {
            const fmt    = FORMAT_COLOR[m.format] ?? FORMAT_COLOR.hf;
            const isCopied = copied === m.uri;
            return (
              <div key={m.id} className="card" style={{ padding: "14px 16px" }}>
                <div className="row" style={{ gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>

                  {/* Format badge */}
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: "3px 7px", borderRadius: 4,
                    background: fmt.bg, color: fmt.text,
                    textTransform: "uppercase", letterSpacing: "0.05em", flexShrink: 0, marginTop: 2,
                  }}>
                    {FORMAT_LABEL[m.format] ?? m.format}
                  </span>

                  {/* Name + base model */}
                  <div style={{ flex: 1, minWidth: 160 }}>
                    <p style={{ fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>{m.name}</p>
                    <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                      {m.base_model}
                      {m.description && <> · {m.description}</>}
                    </p>
                    {m.tags.length > 0 && (
                      <div className="row" style={{ gap: 4, marginTop: 6, flexWrap: "wrap" }}>
                        {m.tags.map((tag) => (
                          <span key={tag} className="pill" style={{ fontSize: 10, padding: "2px 6px" }}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Created */}
                  <span className="muted" style={{ fontSize: 11.5, flexShrink: 0 }}>
                    {new Date(m.created_at).toLocaleDateString()}
                  </span>

                  {/* Copy URI */}
                  <button
                    onClick={() => copyUri(m.uri)}
                    className="btn btn-sm"
                    style={{ flexShrink: 0 }}
                    title={m.uri}
                  >
                    {isCopied ? "Copied!" : "Copy URI"}
                  </button>

                </div>

                {/* R2 URI */}
                <div style={{
                  marginTop: 10, padding: "6px 10px",
                  background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 5,
                }}>
                  <span className="mono muted" style={{ fontSize: 11.5, wordBreak: "break-all" }}>
                    {m.uri}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
}
