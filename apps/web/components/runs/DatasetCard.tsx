"use client";

import { BASE } from "@/lib/api";
import type { DataPrepMetrics } from "@/lib/types";

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

/** data-prep's cleaned dataset: the download link (GET /artifacts/{id}/download) and a stats card from its metrics `fields`. */
export function DatasetCard({ downloadUrl, metrics: m }: { downloadUrl: string | null; metrics: Partial<DataPrepMetrics> }) {
  const dropped = ([["exact duplicates", m.exact_dupes], ["near duplicates", m.near_dupes], ["low quality", m.quality_dropped],
    ["invalid", m.skipped]] as const).filter(([, n]) => n).map(([what, n]) => `${n} ${what}`).join(", ");

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card row" style={{ padding: 16, gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="muted row" style={{ fontSize: 12, gap: 6 }}>
            Dataset
            {m.stub && <span className="pill warn" title="This run ran with STUB=1: placeholder rows">STUB</span>}
          </div>
          <div className="tnum" style={{ fontSize: 28, fontWeight: 600 }}>{m.total ?? "–"} rows</div>
          {m.total != null && (
            <div className="muted tnum" style={{ fontSize: 12.5 }}>
              train {m.train} · eval {m.eval} · test {m.test}{dropped && ` · dropped ${dropped}`}
            </div>
          )}
        </div>
        <div className="spacer" />
        {downloadUrl && (
          <a className="btn btn-primary" href={`${BASE}${downloadUrl}`} style={{ textDecoration: "none" }}>
            Download dataset (JSONL)
          </a>
        )}
      </div>

      {m.fields && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
          {Object.entries(m.fields).map(([name, f]) => (
            <div key={name} className="card" style={{ padding: 14 }}>
              <div className="row">
                <span className="mono" style={{ fontWeight: 600, fontSize: 13 }}>{name}</span>
                <div className="spacer" />
                <span className="muted tnum" style={{ fontSize: 12 }}>{f.distinct} distinct · {f.nulls} null</span>
              </div>
              {f.min != null && <div className="muted mono" style={{ fontSize: 11.5, marginTop: 4 }}>{show(f.min)} → {show(f.max)}</div>}
              {f.top[0]?.[1] === 1 ? <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>Every value is different.</p> : (
                <div className="col" style={{ gap: 4, marginTop: 10 }}>
                  {f.top.map(([value, n]) => (
                    <div key={show(value)} className="row" style={{ gap: 8, fontSize: 12 }}>
                      <span className="mono" title={show(value)}
                        style={{ width: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{show(value)}</span>
                      <div style={{ flex: 1, height: 8, background: "var(--bg-3)", borderRadius: 2 }}>
                        <div style={{ width: `${(n / (m.total || n)) * 100}%`, height: "100%", background: "var(--brand-2)", borderRadius: 2 }} />
                      </div>
                      <span className="muted tnum" style={{ width: 44, textAlign: "right" }}>{n}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
