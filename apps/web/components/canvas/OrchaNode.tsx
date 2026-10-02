"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import type { NodeType } from "@/lib/types";
import { Database, Zap, GitMerge, Package, BarChart2, Globe, Download, Upload, Cloud, Sparkles, Tag, HardDrive } from "lucide-react";

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
  accent: string;   // left border + icon color
  iconBg: string;
}> = {
  // Data ingestion
  "hf-download":          { label: "HF Download",    icon: Download,  accent: "#FF991F", iconBg: "#FFFAE6" },
  "hf-import":            { label: "HF Import",      icon: HardDrive, accent: "#FF991F", iconBg: "#FFFAE6" },
  "file-upload":          { label: "File Upload",    icon: Upload,    accent: "#0065FF", iconBg: "#DEEBFF" },
  "s3-import":            { label: "S3 Import",      icon: Cloud,     accent: "#00B8D9", iconBg: "#E6FCFF" },
  // Data processing
  "data-prep":            { label: "Data Prep",      icon: Database,  accent: "#0065FF", iconBg: "#DEEBFF" },
  "auto-label-cleanlab":  { label: "Auto-Label",     icon: Tag,       accent: "#6554C0", iconBg: "#EAE6FF" },
  "synth-distilabel":     { label: "Synth Data",     icon: Sparkles,  accent: "#00875A", iconBg: "#E3FCEF" },
  // Training
  "unsloth-train":        { label: "Train",          icon: Zap,       accent: "#6554C0", iconBg: "#EAE6FF" },
  "distill-sft":          { label: "Distill",        icon: GitMerge,  accent: "#00B8D9", iconBg: "#E6FCFF" },
  // Post-training
  "quantize":             { label: "Quantize",       icon: Package,   accent: "#FF8B00", iconBg: "#FFFAE6" },
  "lm-eval":              { label: "Evaluate",       icon: BarChart2, accent: "#00875A", iconBg: "#E3FCEF" },
  "vllm-serve":           { label: "Serve",          icon: Globe,     accent: "#DE350B", iconBg: "#FFEBE6" },
};

export function OrchaNode({ data, selected }: NodeProps<Node<OrchaNodeData>>) {
  const meta = NODE_META[data.node_type] ?? NODE_META["data-prep"];
  const Icon = meta.icon;
  const status = data.status;

  const STATUS_RING: Record<string, string> = {
    running:   "ring-2 ring-[#0052CC] ring-offset-1",
    succeeded: "ring-2 ring-[#00875A] ring-offset-1",
    failed:    "ring-2 ring-[#DE350B] ring-offset-1",
  };
  const statusRing = status ? (STATUS_RING[status] ?? "") : "";

  return (
    <div
      className={clsx(
        "min-w-[160px] bg-white rounded shadow-md cursor-pointer select-none transition-all",
        "border border-[#DFE1E6]",
        selected && "ring-2 ring-[#0052CC] ring-offset-1",
        statusRing
      )}
      style={{ borderLeft: `3px solid ${meta.accent}` }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !border-2 !border-[#DFE1E6] !bg-white"
      />

      <div className="px-3 py-2.5 flex items-center gap-2.5">
        <div
          className="w-7 h-7 rounded flex items-center justify-center shrink-0"
          style={{ backgroundColor: meta.iconBg }}
        >
          <Icon className="w-4 h-4" style={{ color: meta.accent }} />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-[#172B4D] truncate">{meta.label}</p>
          <p className="text-[10px] text-[#97A0AF] truncate font-mono">{data.label}</p>
        </div>
      </div>

      {status && status !== "pending" && (
        <div className="px-3 pb-2 flex items-center gap-1.5">
          <div className={clsx(
            "w-1.5 h-1.5 rounded-full",
            status === "running"   && "animate-pulse",
          )} style={{
            backgroundColor:
              status === "running" ? "#0052CC" :
              status === "succeeded" ? "#00875A" : "#DE350B"
          }} />
          <span className="text-[10px] text-[#6B778C] capitalize">{status}</span>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !border-2 !border-[#DFE1E6] !bg-white"
      />
    </div>
  );
}
