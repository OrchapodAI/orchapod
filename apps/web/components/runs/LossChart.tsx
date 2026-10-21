"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { api, toastError } from "@/lib/api";
import { lossPoints, lossSources, TRAINERS } from "@/lib/results";
import { finished } from "@/lib/runEvents";
import type { RunSummary, WsEvent } from "@/lib/types";

/** Training loss: each fine-tune node's loss_curve on load (finished and seeded runs; events have no replay), then live
 *  `progress` events. */
export function LossChart({ summary, events }: { summary: RunSummary; events: WsEvent[] }) {
  const sources = lossSources(summary);
  const urls = sources.flatMap((s) => (s.url ? [s.url] : [])).join("\n"); // a stable effect dependency
  const [files, setFiles] = useState<Record<string, unknown[]>>({});

  // A curve that is not in the metrics meta is in the file behind its download link (fetched once, when the tab opens).
  // Keep it: write_metrics drops its meta above 16 KB (packages/sdk-py/orchapod/io.py), so a long curve from any trainer lives only in the file.
  useEffect(() => {
    let live = true;
    for (const url of urls ? urls.split("\n") : []) {
      api.artifacts.content<{ loss_curve?: unknown }>(url)
        .then((m) => { if (live) setFiles((f) => ({ ...f, [url]: Array.isArray(m?.loss_curve) ? m.loss_curve : [] })); })
        .catch((err) => {
          if (!live) return;
          setFiles((f) => ({ ...f, [url]: [] }));
          toastError("Couldn't load the loss curve")(err);
        });
    }
    return () => { live = false; };
  }, [urls]);

  const curves = sources.flatMap(({ node_id, rows, url }) => {
    const r = rows ?? (url ? files[url] : undefined);
    return r ? [{ node_id, rows: r }] : [];
  });
  const data = lossPoints(curves, events);

  if (data.length === 0) {
    const loading = sources.some((s) => s.url && !(s.url in files));
    return (
      <div className="flex items-center justify-center h-full text-slate-700 text-sm">
        {loading ? "Loading the loss curve…"
          : !summary.nodes.some((n) => TRAINERS.has(n.type)) ? "This run has no training node, so there is no loss to chart."
          : finished(summary.status) ? "No loss was recorded for this run."
          : "Loss chart will appear once training starts"}
      </div>
    );
  }

  const valid = data.some((p) => p.valid_loss !== undefined); // Token Factory checkpoints also report validation loss
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis
          dataKey="step"
          tick={{ fill: "#64748b", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#1e293b" }}
          label={{ value: "Step", position: "insideBottomRight", offset: -4, fill: "#475569", fontSize: 10 }}
        />
        <YAxis
          tick={{ fill: "#64748b", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={40}
          tickFormatter={(v: number) => v.toFixed(2)}
        />
        <Tooltip
          contentStyle={{
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: "8px",
            fontSize: "12px",
            color: "#e2e8f0",
          }}
          labelFormatter={(step) => `Step ${step}`}
          formatter={(v: number, name: string) => [v.toFixed(4), name]}
        />
        {valid && <Legend wrapperStyle={{ fontSize: 12 }} />}
        <Line
          type="monotone"
          dataKey="loss"
          name="train loss"
          stroke="#a78bfa"
          strokeWidth={2}
          dot={data.length <= 20}
          connectNulls
          activeDot={{ r: 4, fill: "#a78bfa", stroke: "#0f172a", strokeWidth: 2 }}
        />
        {valid && (
          <Line type="monotone" dataKey="valid_loss" name="valid loss" stroke="#10b981" strokeWidth={2} dot={data.length <= 20} connectNulls />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
