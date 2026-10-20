"use client";

import type { NodeType } from "@/lib/types";
import { NODE_META } from "./OrchaNode";

// Demo path first. Hidden (no container): hf-import, file-upload, s3-import, auto-label-cleanlab.
const PALETTE_ITEMS: { type: NodeType; description: string; runtime: "cpu" | "gpu" | "api" }[] = [
  { type: "web-research",     description: "Tavily search + extract into a passage corpus",       runtime: "cpu" },
  { type: "synth-distilabel", description: "Generate data with Nemotron teacher (Token Factory)", runtime: "cpu" },
  { type: "data-prep",        description: "Validate, reformat, dedup & split dataset",          runtime: "cpu" },
  { type: "tf-finetune",      description: "LoRA fine-tune on Nebius Token Factory",             runtime: "api" },
  { type: "tf-deploy",        description: "Serve the LoRA per token on Token Factory",          runtime: "api" },
  { type: "judge-eval",       description: "Base vs tuned, judged by Nemotron Ultra",            runtime: "api" },
  { type: "hf-download",      description: "Download HF model to R2 (once, reuse)",              runtime: "cpu" },
  { type: "unsloth-train",    description: "LoRA SFT via Unsloth (2–5× faster, 80% less VRAM)",  runtime: "gpu" },
  { type: "distill-sft",      description: "Teacher → student knowledge distillation",           runtime: "gpu" },
  { type: "quantize",         description: "GGUF (Ollama) or AWQ (vLLM)",                        runtime: "cpu" },
  { type: "vllm-serve",       description: "OpenAI-compatible endpoint via vLLM on Nebius",      runtime: "gpu" },
  { type: "lm-eval",          description: "lm-evaluation-harness benchmarks",                   runtime: "gpu" },
];

const RUNTIME_BADGE = {
  cpu: "bg-[#EBECF0] text-[#6B778C]",
  gpu: "bg-[#EAE6FF] text-[#6554C0]",
  api: "bg-[#DEEBFF] text-[#0052CC]",
};

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
          const { label, icon: Icon, accent, iconBg } = NODE_META[item.type];
          return (
            <div
              key={item.type}
              draggable
              onDragStart={(e) => onDragStart(e, item.type)}
              className="flex items-start gap-2.5 p-2.5 rounded border border-[#DFE1E6] bg-white cursor-grab active:cursor-grabbing hover:border-[#0052CC] hover:shadow-sm transition-all"
            >
              <div
                className="w-6 h-6 rounded flex items-center justify-center shrink-0 mt-0.5"
                style={{ backgroundColor: iconBg }}
              >
                <Icon className="w-3.5 h-3.5" style={{ color: accent }} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#172B4D]">{label}</p>
                <p className="text-[10px] text-[#6B778C] mt-0.5 leading-tight">{item.description}</p>
                <span className={`mt-1 inline-block text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ${RUNTIME_BADGE[item.runtime]}`}>
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
