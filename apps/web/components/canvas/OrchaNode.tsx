"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import type { NodeType } from "@/lib/types";
import {
  Database, Zap, GitMerge, Package, BarChart2, Globe,
} from "lucide-react";

export interface OrchaNodeData extends Record<string, unknown> {
  node_type: NodeType;
  label: string;
  inputs: Record<string, unknown>;
  resources: Record<string, unknown>;
  status?: "pending" | "running" | "succeeded" | "failed";
}

const NODE_META: Record<NodeType, {
  label: string;
  icon: React.ElementType;
  color: string;      // border + icon tint
  bg: string;         // card background
}> = {
  "data-prep":      { label: "Data Prep",    icon: Database,  color: "border-sky-500/60 text-sky-400",     bg: "bg-sky-950/40" },
  "unsloth-train":  { label: "Train",         icon: Zap,       color: "border-violet-500/60 text-violet-400", bg: "bg-violet-950/40" },
  "distill-sft":    { label: "Distill",       icon: GitMerge,  color: "border-fuchsia-500/60 text-fuchsia-400", bg: "bg-fuchsia-950/40" },
  "quantize":       { label: "Quantize",      icon: Package,   color: "border-amber-500/60 text-amber-400",  bg: "bg-amber-950/40" },
  "lm-eval":        { label: "Evaluate",      icon: BarChart2, color: "border-emerald-500/60 text-emerald-400", bg: "bg-emerald-950/40" },
  "vllm-serve":     { label: "Serve",         icon: Globe,     color: "border-rose-500/60 text-rose-400",   bg: "bg-rose-950/40" },
};

const STATUS_RING: Record<string, string> = {
  running:   "ring-2 ring-blue-500/60 ring-offset-2 ring-offset-slate-950",
  succeeded: "ring-2 ring-emerald-500/60 ring-offset-2 ring-offset-slate-950",
  failed:    "ring-2 ring-red-500/60 ring-offset-2 ring-offset-slate-950",
};

export function OrchaNode({ data, selected }: NodeProps<OrchaNodeData>) {
  const meta = NODE_META[data.node_type] ?? NODE_META["data-prep"];
  const Icon = meta.icon;
  const status = data.status;

  return (
    <div
      className={clsx(
        "min-w-[160px] rounded-xl border-2 px-4 py-3 shadow-xl cursor-pointer select-none transition-all",
        meta.bg,
        meta.color,
        selected && "ring-2 ring-violet-400 ring-offset-2 ring-offset-slate-950",
        status && STATUS_RING[status]
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-600 !w-2.5 !h-2.5 !border-slate-500" />

      <div className="flex items-center gap-2.5">
        <div className={clsx("w-7 h-7 rounded-lg flex items-center justify-center shrink-0", meta.bg, "border", meta.color.split(" ")[0])}>
          <Icon className={clsx("w-4 h-4", meta.color.split(" ")[1])} />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-200 truncate">{meta.label}</p>
          <p className="text-[10px] text-slate-500 truncate font-mono">{data.label}</p>
        </div>
      </div>

      {/* Status dot */}
      {status && status !== "pending" && (
        <div className="mt-2 flex items-center gap-1.5">
          <div className={clsx(
            "w-1.5 h-1.5 rounded-full",
            status === "running"   && "bg-blue-400 animate-pulse",
            status === "succeeded" && "bg-emerald-400",
            status === "failed"    && "bg-red-400",
          )} />
          <span className="text-[10px] text-slate-500 capitalize">{status}</span>
        </div>
      )}

      <Handle type="source" position={Position.Right} className="!bg-slate-600 !w-2.5 !h-2.5 !border-slate-500" />
    </div>
  );
}
