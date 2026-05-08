"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

export interface ProgressPoint {
  step: number;
  loss: number;
  node_id: string;
}

interface Props {
  data: ProgressPoint[];
}

export function LossChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-700 text-sm">
        Loss chart will appear once training starts
      </div>
    );
  }

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
          formatter={(v: number) => [v.toFixed(4), "Loss"]}
        />
        <Line
          type="monotone"
          dataKey="loss"
          stroke="#a78bfa"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: "#a78bfa", stroke: "#0f172a", strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
