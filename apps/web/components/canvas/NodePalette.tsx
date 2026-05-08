"use client";

import { Database, Zap, GitMerge, Package, BarChart2, Globe } from "lucide-react";
import type { NodeType } from "@/lib/types";

interface PaletteItem {
  type: NodeType;
  label: string;
  description: string;
  icon: React.ElementType;
  color: string;
  runtime: "cpu" | "gpu";
}

const PALETTE_ITEMS: PaletteItem[] = [
  {
    type: "data-prep",
    label: "Data Prep",
    description: "Load, validate & reformat dataset",
    icon: Database,
    color: "text-sky-400 bg-sky-950/60 border-sky-800",
    runtime: "cpu",
  },
  {
    type: "unsloth-train",
    label: "Train",
    description: "LoRA SFT via Unsloth (2-5× faster)",
    icon: Zap,
    color: "text-violet-400 bg-violet-950/60 border-violet-800",
    runtime: "gpu",
  },
  {
    type: "distill-sft",
    label: "Distill",
    description: "Teacher → student knowledge distillation",
    icon: GitMerge,
    color: "text-fuchsia-400 bg-fuchsia-950/60 border-fuchsia-800",
    runtime: "gpu",
  },
  {
    type: "quantize",
    label: "Quantize",
    description: "GGUF (Ollama) or AWQ (vLLM)",
    icon: Package,
    color: "text-amber-400 bg-amber-950/60 border-amber-800",
    runtime: "cpu",
  },
  {
    type: "lm-eval",
    label: "Evaluate",
    description: "Benchmarks + LLM-as-judge",
    icon: BarChart2,
    color: "text-emerald-400 bg-emerald-950/60 border-emerald-800",
    runtime: "gpu",
  },
  {
    type: "vllm-serve",
    label: "Serve",
    description: "OpenAI-compatible endpoint via vLLM",
    icon: Globe,
    color: "text-rose-400 bg-rose-950/60 border-rose-800",
    runtime: "gpu",
  },
];

interface Props {
  onDragStart: (e: React.DragEvent, type: NodeType) => void;
}

export function NodePalette({ onDragStart }: Props) {
  return (
    <div className="w-56 shrink-0 bg-slate-900/80 border-r border-slate-800 flex flex-col">
      <div className="px-4 py-3 border-b border-slate-800">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Node Palette</p>
        <p className="text-[10px] text-slate-600 mt-0.5">Drag onto canvas</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {PALETTE_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.type}
              draggable
              onDragStart={(e) => onDragStart(e, item.type)}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-grab active:cursor-grabbing hover:opacity-90 transition-opacity ${item.color}`}
            >
              <Icon className="w-4 h-4 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-xs font-semibold text-slate-200">{item.label}</p>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">{item.description}</p>
                <span className={`mt-1 inline-block text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
                  item.runtime === "gpu"
                    ? "bg-violet-900/50 text-violet-400"
                    : "bg-slate-800 text-slate-500"
                }`}>
                  {item.runtime.toUpperCase()}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
