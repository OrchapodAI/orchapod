"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, explainError, toastError } from "@/lib/api";
import type { ArtifactListItem } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  model:    "Model",
  dataset:  "Dataset",
  metrics:  "Metrics",
  log:      "Log",
  endpoint: "Endpoint",
};

const KIND_COLOR: Record<string, { bg: string; text: string }> = {
  model:    { bg: "var(--brand-soft)",  text: "var(--brand-ink)"  },
  dataset:  { bg: "var(--mint-soft)",   text: "var(--mint-ink)"   },
  metrics:  { bg: "#fef3c7",            text: "#92400e"            },
  log:      { bg: "var(--bg-2)",        text: "var(--ink-3)"      },
  endpoint: { bg: "#ede9fe",            text: "#5b21b6"            },
};

const KIND_FILTERS = ["all", "model", "dataset", "metrics", "log", "endpoint"] as const;

function fmtBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<ArtifactListItem[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [search,    setSearch]    = useState("");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [copied,    setCopied]    = useState<string | null>(null);
  const [error,     setError]     = useState("");

  useEffect(() => {
    api.artifacts.list({ limit: 200 })
      .then(setArtifacts)
      .catch((err) => { setError(explainError(err)); toastError("Couldn't load artifacts")(err); })
      .finally(() => setLoading(false));
  }, []);

  function copyUri(uri: string) {
    navigator.clipboard.writeText(uri).then(() => {
      setCopied(uri);
      setTimeout(() => setCopied(null), 2000);
    }).catch(toastError("Couldn't copy the URI"));
  }

  const filtered = artifacts.filter((a) => {
    const matchKind = kindFilter === "all" || a.kind === kindFilter;
    const matchSearch = !search || [a.name, a.uri, a.workflow_name ?? "", a.node_id]
      .some((s) => s.toLowerCase().includes(search.toLowerCase()));
    return matchKind && matchSearch;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="op-topbar">
        <div className="op-crumbs"><span>Artifacts</span></div>
        <div className="spacer" />
        <span className="muted" style={{ fontSize: 12 }}>{loading ? "…" : `${artifacts.length} total`}</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>

        {/* Filters */}
        <div className="row" style={{ gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
          <input
            type="search"
            placeholder="Search by name, URI, workflow, node…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1, minWidth: 220, padding: "7px 10px", fontSize: 13,
              border: "1px solid var(--line)", borderRadius: 6,
              background: "var(--bg-2)", color: "var(--ink-1)", outline: "none",
            }}
          />
          {KIND_FILTERS.map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className="btn btn-sm"
              style={{
                fontWeight:  kindFilter === k ? 600 : 400,
                background:  kindFilter === k ? "var(--brand-soft)"  : undefined,
                color:       kindFilter === k ? "var(--brand-ink)"   : undefined,
                borderColor: kindFilter === k ? "var(--brand)"       : undefined,
              }}
            >
              {k === "all" ? "All types" : KIND_LABEL[k]}
            </button>
          ))}
        </div>

        {/* States */}
        {loading && <p className="muted" style={{ fontSize: 13 }}>Loading…</p>}

        {!loading && artifacts.length === 0 && (
          <div style={{ textAlign: "center", marginTop: 64 }}>
            <p style={{ fontSize: 15, fontWeight: 500 }}>{error ? "Couldn't load artifacts" : "No artifacts yet"}</p>
            <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {error || "Artifacts are produced when workflow runs complete."}
            </p>
            {!error && (
              <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                Press Run on a template on the <Link href="/agent" style={{ color: "var(--brand)", textDecoration: "underline" }}>Agent</Link> page to make a dataset, a model or an eval.
              </p>
            )}
          </div>
        )}

        {!loading && artifacts.length > 0 && filtered.length === 0 && (
          <p className="muted" style={{ fontSize: 13 }}>No artifacts match your filters.</p>
        )}

        {/* Artifact list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((a) => {
            const kc = KIND_COLOR[a.kind] ?? KIND_COLOR.log;
            const isCopied = copied === a.uri;
            return (
              <div key={a.id} className="card" style={{ padding: "12px 16px" }}>
                <div className="row" style={{ gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>

                  {/* Kind badge */}
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: "3px 7px", borderRadius: 4,
                    background: kc.bg, color: kc.text, textTransform: "uppercase",
                    letterSpacing: "0.05em", flexShrink: 0, marginTop: 2,
                  }}>
                    {KIND_LABEL[a.kind] ?? a.kind}
                  </span>

                  {/* Name + provenance */}
                  <div style={{ flex: 1, minWidth: 160 }}>
                    <p style={{ fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>{a.name}</p>
                    <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                      {a.workflow_name && (
                        <>
                          <Link href={`/runs/${a.run_id}`} style={{ color: "var(--brand)" }}>
                            {a.workflow_name}
                          </Link>
                          {" · "}
                        </>
                      )}
                      {a.node_id}
                      {a.size_bytes != null && ` · ${fmtBytes(a.size_bytes)}`}
                    </p>
                  </div>

                  {/* Date */}
                  <span className="muted" style={{ fontSize: 11.5, flexShrink: 0 }}>
                    {new Date(a.created_at).toLocaleDateString()}
                  </span>

                  {/* View run */}
                  <Link
                    href={`/runs/${a.run_id}`}
                    className="btn btn-sm"
                    style={{ textDecoration: "none", flexShrink: 0 }}
                  >
                    View run
                  </Link>

                  {/* Copy URI */}
                  <button
                    onClick={() => copyUri(a.uri)}
                    className="btn btn-sm"
                    style={{ flexShrink: 0 }}
                    title={a.uri}
                  >
                    {isCopied ? "Copied!" : "Copy URI"}
                  </button>

                </div>

                {/* URI */}
                <div style={{
                  marginTop: 8, padding: "5px 10px",
                  background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 5,
                }}>
                  <span className="mono muted" style={{ fontSize: 11, wordBreak: "break-all" }}>
                    {a.uri}
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
