"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { InferenceEndpoint } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

function fmtCountdown(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "Expired";
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  return `${m}m`;
}

export default function EndpointsPage() {
  const [endpoints, setEndpoints] = useState<InferenceEndpoint[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [, setTick] = useState(0);

  useEffect(() => {
    api.inference.endpoints()
      .then(setEndpoints)
      .finally(() => setLoading(false));
  }, []);

  // Tick every 30s so countdowns stay roughly fresh
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const live    = endpoints.filter((e) => e.status === "running");
  const expired = endpoints.filter((e) => e.status !== "running");

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="op-topbar">
        <div className="op-crumbs">
          <span>Endpoints</span>
        </div>
        <div className="spacer" />
        <Link href="/inference" className="btn btn-sm" style={{ textDecoration: "none" }}>
          + Deploy new
        </Link>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>

        {loading && <p className="muted" style={{ fontSize: 13 }}>Loading…</p>}

        {!loading && endpoints.length === 0 && (
          <div style={{ textAlign: "center", marginTop: 64 }}>
            <p style={{ fontSize: 15, fontWeight: 500 }}>No endpoints yet</p>
            <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              Deploy a model from the{" "}
              <Link href="/inference" style={{ color: "var(--brand)" }}>Inference</Link>{" "}
              page to create one.
            </p>
          </div>
        )}

        {/* Live endpoints */}
        {live.length > 0 && (
          <section style={{ marginBottom: 32 }}>
            <h2 style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-3)", marginBottom: 12 }}>
              Live ({live.length})
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {live.map((ep) => (
                <EndpointRow key={ep.run_id} ep={ep} />
              ))}
            </div>
          </section>
        )}

        {/* Expired / past endpoints */}
        {expired.length > 0 && (
          <section>
            <h2 style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-3)", marginBottom: 12 }}>
              Past ({expired.length})
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {expired.map((ep) => (
                <EndpointRow key={ep.run_id} ep={ep} />
              ))}
            </div>
          </section>
        )}

      </div>
    </div>
  );
}

function EndpointRow({ ep }: { ep: InferenceEndpoint }) {
  const isLive     = ep.status === "running";
  const expiresAt  = (ep as unknown as { expires_at?: string }).expires_at;
  const countdown  = isLive && expiresAt ? fmtCountdown(expiresAt) : null;
  const nearExpiry = countdown && !countdown.startsWith("E") && parseInt(countdown) <= 10;

  return (
    <div className="card" style={{ padding: "14px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      {/* Status dot */}
      <span style={{
        width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
        background: isLive ? "var(--mint)" : "var(--ink-4)",
      }} />

      {/* Model + provider */}
      <div style={{ flex: 1, minWidth: 160 }}>
        <p style={{ fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>{ep.model}</p>
        <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
          {ep.workflow_name}
          {ep.gpu_provider && ` · ${ep.gpu_provider}`}
          {ep.started_at && ` · Started ${new Date(ep.started_at).toLocaleString()}`}
        </p>
      </div>

      {/* Countdown */}
      {countdown && (
        <span style={{
          fontSize: 12, fontWeight: 600, padding: "3px 8px", borderRadius: 5,
          background: nearExpiry ? "var(--rose-soft)" : "var(--mint-soft)",
          color:      nearExpiry ? "var(--rose-ink)"  : "var(--mint-ink)",
          border:     `1px solid ${nearExpiry ? "var(--rose)" : "var(--mint)"}`,
        }}>
          ⏱ {countdown}
        </span>
      )}

      {/* Endpoint URL */}
      {ep.endpoint_url && (
        <a
          href={ep.endpoint_url.replace(/\/v1\/?$/, "")}
          target="_blank" rel="noreferrer"
          className="btn btn-sm"
          style={{ textDecoration: "none", color: "var(--mint-ink)", background: "var(--mint-soft)", borderColor: "var(--mint)", flexShrink: 0 }}
        >
          Open ↗
        </a>
      )}

      {/* View run */}
      <Link
        href={`/runs/${ep.run_id}`}
        className="btn btn-sm"
        style={{ textDecoration: "none", flexShrink: 0 }}
      >
        View run
      </Link>
    </div>
  );
}
