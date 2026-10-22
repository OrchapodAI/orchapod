"use client";

import type { ReactNode } from "react";
import { X, ExternalLink } from "lucide-react";
import type { Node } from "@xyflow/react";
import type { OrchaNodeData } from "./OrchaNode";
import { NODE_FORMS, type FormField } from "@/lib/nodeForms";

interface Props {
  node: Node<OrchaNodeData>;
  onClose: () => void;
  onUpdate: (id: string, data: Partial<OrchaNodeData>) => void;
}

const FIELD_LABELS: Record<string, string> = {
  model: "Base model (HF ID)", train_data: "Train data URI", eval_data: "Eval data URI",
  lora_r: "LoRA rank (r)", lora_alpha: "LoRA alpha", max_steps: "Max steps",
  learning_rate: "Learning rate", target_modules: "Target modules",
  dataset: "Dataset URI", format: "Data format", train_split: "Train split",
  teacher: "Teacher model URI", student_base: "Student base model", n_synthetic: "Synthetic examples",
  method: "Quantize method", precision: "GGUF precision", bits: "AWQ bits",
  models: "Models to evaluate", tasks: "Eval tasks", judge_eval_set: "Judge eval set URI",
  max_model_len: "Max model length", keep_alive_min: "Keep-alive (minutes)",
};

const INPUT_CLASS = "w-full bg-white border border-[#DFE1E6] rounded px-3 py-2 text-xs text-[#172B4D] focus:outline-none focus:border-[#0052CC] focus:ring-2 focus:ring-[#0052CC]/20 transition-colors";

const asText = (v: unknown) => v == null ? "" : typeof v === "string" ? v : JSON.stringify(v, null, 2);

// JSON when it parses (objects, ModelRefs), else the text as typed (refs, model ids, URIs).
function parseLoose(text: string): unknown {
  try { return JSON.parse(text); } catch { return text; }
}

// Uncontrolled on purpose (defaultValue), so parsing never moves the caret; the panel is keyed by node.
// One panel is open at a time, so help-<key> ids are unique.
function FormInput({ field: f, value, onChange }: { field: FormField; value: unknown; onChange: (v: unknown) => void }) {
  const help = { "aria-describedby": `help-${f.key}` };
  switch (f.kind) {
    case "bool":
      return <input type="checkbox" {...help} defaultChecked={Boolean(value ?? f.default)} onChange={(e) => onChange(e.target.checked)} />;
    case "number":
      // focus:invalid: too, or the focus border hides the red one while the user types
      return <input type="number" step="any" max={f.max} {...help} defaultValue={asText(value)} placeholder={f.placeholder}
        aria-invalid={f.max != null && Number(value) > f.max ? true : undefined}
        className={`${INPUT_CLASS} invalid:border-[#DE350B] focus:invalid:border-[#DE350B]`}
        onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.valueAsNumber)} />;
    case "list":
      return <textarea rows={3} {...help} defaultValue={Array.isArray(value) ? value.join("\n") : asText(value)} className={INPUT_CLASS}
        onChange={(e) => onChange(e.target.value.split("\n").map((l) => l.trim()).filter(Boolean))} />;
    case "json":
      return <textarea rows={typeof value === "object" ? 4 : 2} {...help} defaultValue={asText(value)} className={`${INPUT_CLASS} font-mono`}
        onChange={(e) => onChange(parseLoose(e.target.value))} />;
    default:
      return <input {...help} defaultValue={asText(value)} placeholder={f.placeholder} className={INPUT_CLASS}
        onChange={(e) => onChange(e.target.value === "" && f.default === undefined ? undefined : e.target.value)} />;
  }
}

export function NodePanel({ node, onClose, onUpdate }: Props) {
  const data: OrchaNodeData = node.data as OrchaNodeData;
  const inputs: Record<string, unknown> = (data.inputs as Record<string, unknown>) ?? {};
  const form = NODE_FORMS[data.node_type];
  const inputEntries: [string, unknown][] = Object.entries(inputs);
  const resourceEntries: [string, unknown][] = Object.entries(
    (data.resources as Record<string, unknown>) ?? {}
  );

  const inputsSection: ReactNode = form ? (
    <div>
      <p className="text-xs font-semibold text-[#6B778C] uppercase tracking-wide mb-3">Inputs</p>
      <div className="space-y-3">
        {form.map((f) => (
          <div key={f.key}>
            <label className="block">
              <span className="block text-xs font-medium text-[#172B4D] mb-1.5">
                {f.label} <span className="font-mono font-normal text-[#97A0AF]">{f.key}</span>
              </span>
              <FormInput field={f} value={inputs[f.key]} onChange={(v) => setInput(f.key, v)} />
            </label>
            <p id={`help-${f.key}`} className="text-[10.5px] text-[#6B778C] mt-1 leading-snug">{f.help}</p>
          </div>
        ))}
      </div>
    </div>
  ) : inputEntries.length > 0 ? (
    <div>
      <p className="text-xs font-semibold text-[#6B778C] uppercase tracking-wide mb-3">Inputs</p>
      <div className="space-y-3">
        {inputEntries.map(([key, val]) => (
          <div key={key}>
            <label className="block text-xs font-medium text-[#172B4D] mb-1.5">
              {FIELD_LABELS[key] ?? key}
            </label>
            <input
              value={val !== null && typeof val === "object" ? JSON.stringify(val) : String(val ?? "")}
              onChange={(e) => handleChange(key, e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
        ))}
      </div>
    </div>
  ) : null;

  const resourcesSection: ReactNode = resourceEntries.length > 0 ? (
    <div>
      <p className="text-xs font-semibold text-[#6B778C] uppercase tracking-wide mb-3">Resources</p>
      <div className="bg-[#F4F5F7] rounded border border-[#DFE1E6] p-3 space-y-1.5">
        {resourceEntries.map(([k, v]) => (
          <div key={k} className="flex justify-between text-xs">
            <span className="text-[#6B778C]">{k}</span>
            <span className="text-[#172B4D] font-mono">{String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  ) : null;

  function handleChange(key: string, value: string) {
    onUpdate(node.id, { inputs: { ...inputs, [key]: value } });
  }

  // undefined drops the input, so the node's own default applies.
  function setInput(key: string, value: unknown) {
    onUpdate(node.id, { inputs: Object.fromEntries(Object.entries({ ...inputs, [key]: value }).filter(([, v]) => v !== undefined)) });
  }

  return (
    <div className="w-72 shrink-0 bg-white border-l border-[#DFE1E6] flex flex-col overflow-hidden shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#DFE1E6] bg-[#F4F5F7]">
        <div>
          <p className="text-sm font-semibold text-[#172B4D] capitalize">
            {data.node_type.replace(/-/g, " ")}
          </p>
          <p className="text-xs text-[#6B778C] font-mono">{data.label}</p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded text-[#6B778C] hover:text-[#172B4D] hover:bg-[#DFE1E6] transition-colors"
          style={{ cursor: "pointer" }}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Fields */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Node ID */}
        <div>
          <label className="block text-xs font-semibold text-[#6B778C] uppercase tracking-wide mb-1.5">Node ID</label>
          <input
            value={data.label}
            readOnly
            className="w-full bg-[#F4F5F7] border border-[#DFE1E6] rounded px-3 py-2 text-xs text-[#6B778C] font-mono cursor-not-allowed"
          />
        </div>

        {/* Inputs */}
        {inputsSection}

        {/* Resources */}
        {resourcesSection}

        {(data.node_type === "unsloth-train" || data.node_type === "distill-sft") &&
          typeof inputs.model === "string" && inputs.model &&
          !inputs.model.includes("${{") ? (
          <a
            href={`https://huggingface.co/${inputs.model}`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 text-xs text-[#0052CC] hover:underline"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            View on Hugging Face
          </a>
        ) : null}
      </div>
    </div>
  );
}
