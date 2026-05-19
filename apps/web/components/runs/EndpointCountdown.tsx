"use client";

/**
 * EndpointCountdown — KAN-30
 *
 * Live countdown to endpoint expiry. Shows a warning banner at T-10min.
 * "Extend by 1 hour" button hits POST /inference/extend/{run_id},
 * previews cost before confirming.
 *
 * Props:
 *   runId      — used for the extend API call
 *   expiresAt  — ISO-8601 UTC string from artifact meta
 *   onExtended — callback with new expiresAt string after a successful extend
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Props {
  runId:      string;
  expiresAt:  string;
  onExtended: (newExpiresAt: string) => void;
}

function fmtCountdown(ms: number): string {
  if (ms <= 0) return "Expired";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function EndpointCountdown({ runId, expiresAt, onExtended }: Props) {
  const [msLeft,       setMsLeft]       = useState<number>(() => new Date(expiresAt).getTime() - Date.now());
  const [confirming,   setConfirming]   = useState(false);   // cost preview shown
  const [extending,    setExtending]    = useState(false);   // API call in flight
  const [costPreview,  setCostPreview]  = useState<number | null>(null);
  const [extendError,  setExtendError]  = useState<string | null>(null);

  // Tick every second
  useEffect(() => {
    setMsLeft(new Date(expiresAt).getTime() - Date.now());
    const id = setInterval(() => {
      setMsLeft(new Date(expiresAt).getTime() - Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  const expired    = msLeft <= 0;
  const warning    = !expired && msLeft <= 10 * 60 * 1000;   // T-10min
  const critical   = !expired && msLeft <= 2  * 60 * 1000;   // T-2min

  const bgColor    = critical ? "var(--rose-soft)"   : warning ? "#fff7ed"       : "var(--bg-2)";
  const borderColor= critical ? "var(--rose)"        : warning ? "#f97316"       : "var(--line)";
  const textColor  = critical ? "var(--rose-ink)"    : warning ? "#9a3412"       : "var(--ink-2)";

  async function fetchCostPreview() {
    setConfirming(true);
    setExtendError(null);
    try {
      const res = await api.inference.extendPreview(runId, 60);
      setCostPreview(res.cost_estimate_usd);
    } catch {
      // If preview fails, still let them extend — just show no estimate
      setCostPreview(null);
    }
  }

  async function confirmExtend() {
    setExtending(true);
    setExtendError(null);
    try {
      const res = await api.inference.extend(runId, 60);
      setConfirming(false);
      setCostPreview(null);
      // expires_at comes back as a string from the JSON response
      onExtended(String(res.expires_at));
    } catch (err) {
      setExtendError(err instanceof Error ? err.message : "Extend failed");
    } finally {
      setExtending(false);
    }
  }

  return (
    <div style={{
      background:   bgColor,
      border:       `1px solid ${borderColor}`,
      borderRadius: 8,
      padding:      "10px 14px",
      display:      "flex",
      alignItems:   "center",
      gap:          12,
      flexWrap:     "wrap",
    }}>
      {/* Icon + countdown */}
      <span style={{ fontSize: 15 }}>
        {expired ? "⏹" : critical ? "🔴" : warning ? "⚠️" : "⏱"}
      </span>

      <div style={{ flex: 1, minWidth: 120 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: textColor }}>
          {expired ? "Endpoint expired" : `Expires in ${fmtCountdown(msLeft)}`}
        </span>
        {warning && !expired && (
          <p style={{ fontSize: 11.5, color: textColor, margin: "2px 0 0", opacity: 0.85 }}>
            Endpoint will shut down soon — extend now to keep it alive.
          </p>
        )}
      </div>

      {/* Extend flow */}
      {!expired && !confirming && (
        <button
          onClick={fetchCostPreview}
          className="btn btn-sm"
          style={{
            background:   warning ? borderColor : undefined,
            color:        warning ? "#fff"       : undefined,
            borderColor:  warning ? borderColor  : undefined,
          }}
        >
          Extend 1 hr
        </button>
      )}

      {confirming && !extending && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12.5, color: textColor }}>
            {costPreview != null
              ? `~$${costPreview.toFixed(4)} for 1 hr — confirm?`
              : "Extend by 1 hr — confirm?"}
          </span>
          <button onClick={confirmExtend} className="btn btn-sm">Yes, extend</button>
          <button onClick={() => { setConfirming(false); setExtendError(null); }} className="btn btn-sm">Cancel</button>
        </div>
      )}

      {extending && (
        <span className="muted" style={{ fontSize: 12.5 }}>Extending…</span>
      )}

      {extendError && (
        <span style={{ fontSize: 12, color: "var(--rose-ink)" }}>{extendError}</span>
      )}
    </div>
  );
}
