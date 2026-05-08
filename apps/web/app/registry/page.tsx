"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BaseModel, PublicDataset } from "@/lib/types";

type Tab = "models" | "datasets";

export default function RegistryPage() {
  const [tab, setTab] = useState<Tab>("models");
  const [models, setModels] = useState<BaseModel[]>([]);
  const [datasets, setDatasets] = useState<PublicDataset[]>([]);

  useEffect(() => {
    api.registry.models().then((r) => setModels(r.models));
    api.registry.datasets().then((r) => setDatasets(r.datasets));
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Topbar */}
      <div className="op-topbar">
        <div className="op-crumbs">
          <span>orbital-research</span>
          <span className="sep">/</span>
          <span className="here">Registry</span>
        </div>
        <div className="spacer" />
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "24px 24px 0" }}>
          <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>Registry</h1>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>Curated base models and public datasets</div>
        </div>

        {/* Underline tabs */}
        <div className="row" style={{ borderBottom: "1px solid var(--line)", padding: "0 24px", gap: 4, fontSize: 13, marginTop: 16 }}>
          {(["models", "datasets"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: "10px 8px",
                border: "none", background: "transparent",
                borderBottom: tab === t ? "2px solid var(--brand)" : "2px solid transparent",
                color: tab === t ? "var(--brand-ink)" : "var(--ink-3)",
                fontWeight: tab === t ? 500 : 400,
                cursor: "pointer", fontFamily: "var(--font-ui)", fontSize: 13,
                textTransform: "capitalize",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, padding: 24, overflow: "auto" }}>
          {tab === "models" && (
            <div className="card" style={{ overflow: "hidden" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: "30%" }}>Model</th>
                    <th>Family</th>
                    <th>Params</th>
                    <th>Context</th>
                    <th>GPU</th>
                    <th>Use cases</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{m.name}</div>
                        {m.requires_hf_token && (
                          <span className="tag" style={{ background: "var(--amber-soft)", color: "var(--amber-ink)", marginTop: 2 }}>HF Token</span>
                        )}
                      </td>
                      <td className="muted">{m.family}</td>
                      <td className="mono">{m.params_b}B</td>
                      <td className="mono">{(m.context_len / 1000).toFixed(0)}K</td>
                      <td className="muted" style={{ fontSize: 12 }}>{m.recommended_gpu}</td>
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                          {m.use_cases.slice(0, 3).map((uc) => (
                            <span key={uc} className="tag" style={{ background: "var(--bg-3)", color: "var(--ink-2)" }}>{uc}</span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <a
                          href={m.hf_url}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-sm btn-ghost"
                          style={{ textDecoration: "none" }}
                        >
                          HF ↗
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "datasets" && (
            <div className="card" style={{ overflow: "hidden" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: "30%" }}>Dataset</th>
                    <th>Format</th>
                    <th>Size</th>
                    <th>Use cases</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((ds) => (
                    <tr key={ds.id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{ds.name}</div>
                        <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{ds.description}</div>
                      </td>
                      <td><span className="mono tag" style={{ background: "var(--bg-3)", color: "var(--ink-2)" }}>{ds.format}</span></td>
                      <td className="muted">{ds.size}</td>
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                          {ds.use_cases.slice(0, 3).map((uc) => (
                            <span key={uc} className="tag" style={{ background: "var(--bg-3)", color: "var(--ink-2)" }}>{uc}</span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <a
                          href={ds.hf_url}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-sm btn-ghost"
                          style={{ textDecoration: "none" }}
                        >
                          HF ↗
                        </a>
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
