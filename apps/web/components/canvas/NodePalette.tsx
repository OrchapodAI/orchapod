"use client";

import { Database, Zap, GitMerge, Package, BarChart2, Globe, Download, Upload, Cloud, Sparkles, Tag, HardDrive } from "lucide-react";
import type { NodeType } from "@/lib/types";

interface PaletteItem {
  type: NodeType;
  label: string;
  description: string;
  icon: React.ElementType;
  accent: string;
  iconBg: string;
  runtime: "cpu" | "gpu";
}

const PALETTE_ITEMS: PaletteItem[] = [
  // ── Data ingestion ──────────────────────────────────────────────────────────
  { type: "hf-download",         label: "HF Download",  description: "Download HF model to R2 (once, reuse)",              icon: Download,  accent: "#FF991F", iconBg: "#FFFAE6", runtime: "cpu" },
  { type: "hf-import",           label: "HF Import",    description: "Import HuggingFace dataset, auto-detect format",     icon: HardDrive, accent: "#FF991F", iconBg: "#FFFAE6", runtime: "cpu" },
  { type: "file-upload",         label: "File Upload",  description: "Upload CSV / JSONL / Parquet from your computer",    icon: Upload,    accent: "#0065FF", iconBg: "#DEEBFF", runtime: "cpu" },
  { type: "s3-import",           label: "S3 Import",    description: "Read from S3-compatible bucket (AWS / R2 / MinIO)",  icon: Cloud,     accent: "#00B8D9", iconBg: "#E6FCFF", runtime: "cpu" },
  // ── Data processing ─────────────────────────────────────────────────────────
  { type: "data-prep",           label: "Data Prep",    description: "Validate, reformat, dedup & split dataset",          icon: Database,  accent: "#0065FF", iconBg: "#DEEBFF", runtime: "cpu" },
  { type: "synth-distilabel",    label: "Synth Data",   description: "Generate data with Nemotron teacher (Token Factory)", icon: Sparkles,  accent: "#00875A", iconBg: "#E3FCEF", runtime: "cpu" },
  { type: "auto-label-cleanlab", label: "Auto-Label",   description: "Cleanlab TLM quality scores + threshold filter",     icon: Tag,       accent: "#6554C0", iconBg: "#EAE6FF", runtime: "cpu" },
  // ── Training ────────────────────────────────────────────────────────────────
  { type: "unsloth-train",       label: "Train",        description: "LoRA SFT via Unsloth (2–5× faster, 80% less VRAM)", icon: Zap,       accent: "#6554C0", iconBg: "#EAE6FF", runtime: "gpu" },
  { type: "distill-sft",         label: "Distill",      description: "Teacher → student knowledge distillation",           icon: GitMerge,  accent: "#00B8D9", iconBg: "#E6FCFF", runtime: "gpu" },
  // ── Post-training ────────────────────────────────────────────────────────────
  { type: "quantize",            label: "Quantize",     description: "GGUF (Ollama) or AWQ (vLLM)",                        icon: Package,   accent: "#FF8B00", iconBg: "#FFFAE6", runtime: "cpu" },
  { type: "lm-eval",             label: "Evaluate",     description: "Benchmarks + Nemotron Ultra judge",                  icon: BarChart2, accent: "#00875A", iconBg: "#E3FCEF", runtime: "gpu" },
  { type: "vllm-serve",          label: "Serve",        description: "OpenAI-compatible endpoint via vLLM on Nebius",      icon: Globe,     accent: "#DE350B", iconBg: "#FFEBE6", runtime: "gpu" },
];

interface Props {
  onDragStart: (e: React.DragEvent, type: NodeType) => void;
}

export function NodePalette({ onDragStart }: Props) {
  return (
    <div className="w-56 shrink-0 bg-white border-r border-[#DFE1E6] flex flex-col">
      <div className="px-4 py-3 border-b border-[#DFE1E6]">
        <p className="text-xs font-semibold text-[#172B4D] uppercase tracking-wider">Node Palette</p>
        <p className="text-[11px] text-[#97A0AF] mt-0.5">Drag onto canvas</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
        {PALETTE_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.type}
              draggable
              onDragStart={(e) => onDragStart(e, item.type)}
              className="flex items-start gap-2.5 p-2.5 rounded border border-[#DFE1E6] bg-white cursor-grab active:cursor-grabbing hover:border-[#0052CC] hover:shadow-sm transition-all"
            >
              <div
                className="w-6 h-6 rounded flex items-center justify-center shrink-0 mt-0.5"
                style={{ backgroundColor: item.iconBg }}
              >
                <Icon className="w-3.5 h-3.5" style={{ color: item.accent }} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#172B4D]">{item.label}</p>
                <p className="text-[10px] text-[#6B778C] mt-0.5 leading-tight">{item.description}</p>
                <span className={`mt-1 inline-block text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ${
                  item.runtime === "gpu"
                    ? "bg-[#EAE6FF] text-[#6554C0]"
                    : "bg-[#EBECF0] text-[#6B778C]"
                }`}>
                  {item.runtime}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
