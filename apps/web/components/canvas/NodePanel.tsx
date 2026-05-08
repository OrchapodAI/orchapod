"use client";

import { X, ExternalLink } from "lucide-react";
import type { Node } from "@xyflow/react";
import type { OrchaNodeData } from "./OrchaNode";

interface Props {
  node: Node<OrchaNodeData>;
  onClose: () => void;
  onUpdate: (id: string, data: Partial<OrchaNodeData>) => void;
}

const FIELD_LABELS: Record<string, string> = {
  model: "Base model (HF ID)",
  train_data: "Train data URI",
  eval_data: "Eval data URI",
  lora_r: "LoRA rank (r)",
  lora_alpha: "LoRA alpha",
  max_steps: "Max steps",
  learning_rate: "Learning rate",
  target_modules: "Target modules",
  dataset: "Dataset URI",
  format: "Data format",
  train_split: "Train split",
  teacher: "Teacher model URI",
  student_base: "Student base model",
  n_synthetic: "Synthetic examples",
  method: "Quantize method",
  precision: "GGUF precision",
  bits: "AWQ bits",
  models: "Models to evaluate",
  tasks: "Eval tasks",
  judge_eval_set: "Judge eval set URI",
  max_model_len: "Max model length",
  keep_alive_min: "Keep-alive (minutes)",
};

export function NodePanel({ node, onClose, onUpdate }: Props) {
  const { data } = node;
  const inputs = data.inputs ?? {};

  function handleChange(key: string, value: string) {
    onUpdate(node.id, {
      inputs: { ...inputs, [key]: value },
    });
  }

  return (
    <div className="w-72 shrink-0 bg-slate-900/90 border-l border-slate-800 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div>
          <p className="text-sm font-semibold text-slate-100 capitalize">
            {data.node_type.replace("-", " ")}
          </p>
          <p className="text-xs text-slate-500 font-mono">{data.label}</p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Fields */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Node ID */}
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Node ID</label>
          <input
            value={data.label}
            readOnly
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-500 font-mono cursor-not-allowed"
          />
        </div>

        {/* Inputs */}
        {Object.keys(inputs).length > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Inputs</p>
            <div className="space-y-3">
              {Object.entries(inputs).map(([key, val]) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">
                    {FIELD_LABELS[key] ?? key}
                  </label>
                  <input
                    value={String(val ?? "")}
                    onChange={(e) => handleChange(key, e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-600 transition-colors"
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Resources */}
        {data.resources && Object.keys(data.resources).length > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Resources</p>
            <div className="bg-slate-950 rounded-lg border border-slate-800 p-3 space-y-1.5">
              {Object.entries(data.resources).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs">
                  <span className="text-slate-500">{k}</span>
                  <span className="text-slate-300 font-mono">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* HF link for train/distill nodes */}
        {(data.node_type === "unsloth-train" || data.node_type === "distill-sft") && inputs.model && (
          <a
            href={`https://huggingface.co/${inputs.model}`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            View on Hugging Face
          </a>
        )}
      </div>
    </div>
  );
}
