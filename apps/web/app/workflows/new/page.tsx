"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Code2, ArrowLeft, Loader2, ChevronRight } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import clsx from "clsx";

type Mode = "prompt" | "yaml";

const EXAMPLE_PROMPTS = [
  "Fine-tune Qwen3-4B on my customer support dataset, then deploy as an API",
  "Distill Qwen3-4B into a 1.7B model for edge deployment, quantize to GGUF",
  "Fine-tune Llama 3.1 8B on Python code, evaluate on coding benchmarks, then serve",
];

const STARTER_YAML = `name: my-finetune-workflow
version: 1
inputs:
  dataset_uri:
    type: string
    description: "JSONL or HuggingFace dataset"
  base_model:
    type: string
    default: "Qwen/Qwen3-4B-Instruct"
nodes:
  - id: prep
    type: data-prep
    inputs:
      dataset: \${{ inputs.dataset_uri }}
      format: chatml
      train_split: 0.9

  - id: train
    type: unsloth-train
    needs: [prep]
    inputs:
      model: \${{ inputs.base_model }}
      train_data: \${{ nodes.prep.outputs.train_jsonl }}
      eval_data: \${{ nodes.prep.outputs.eval_jsonl }}
      lora_r: 16
      max_steps: 500

  - id: eval
    type: lm-eval
    needs: [train]
    inputs:
      models: [\${{ nodes.train.outputs.merged_model }}]
      tasks: [hellaswag, gsm8k]
      judge_eval_set: \${{ nodes.prep.outputs.eval_jsonl }}
`;

export default function NewWorkflowPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("prompt");
  const [prompt, setPrompt] = useState("");
  const [yaml, setYaml] = useState(STARTER_YAML);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let workflow;
      if (mode === "prompt") {
        workflow = await api.workflows.fromPrompt(prompt);
      } else {
        if (!name.trim()) {
          setError("Please enter a workflow name.");
          return;
        }
        workflow = await api.workflows.create({ name: name.trim(), yaml });
      }
      router.push(`/canvas/${workflow.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 w-full">
      {/* Back */}
      <Link
        href="/workflows"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-300 transition-colors mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to workflows
      </Link>

      <h1 className="text-2xl font-semibold text-slate-100 mb-1">New workflow</h1>
      <p className="text-slate-500 text-sm mb-7">
        Describe your fine-tuning goal in plain English, or write YAML directly.
      </p>

      {/* Mode tabs */}
      <div className="flex bg-slate-900 rounded-lg p-1 gap-1 mb-7 border border-slate-800 w-fit">
        {(["prompt", "yaml"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={clsx(
              "flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all",
              mode === m
                ? "bg-violet-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {m === "prompt" ? <Sparkles className="w-3.5 h-3.5" /> : <Code2 className="w-3.5 h-3.5" />}
            {m === "prompt" ? "AI prompt" : "YAML"}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {mode === "prompt" ? (
          <>
            {/* Prompt mode */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Describe your workflow
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={5}
                required
                placeholder="e.g. Fine-tune Qwen3-4B on my customer support dataset, evaluate it, and deploy as an API endpoint."
                className="w-full bg-slate-900 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-violet-600 resize-none transition-colors"
              />
            </div>

            {/* Example prompts */}
            <div>
              <p className="text-xs text-slate-600 mb-2">Examples</p>
              <div className="space-y-2">
                {EXAMPLE_PROMPTS.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => setPrompt(ex)}
                    className="w-full text-left text-xs text-slate-500 hover:text-slate-300 bg-slate-900/50 hover:bg-slate-800 border border-slate-800 rounded-lg px-3 py-2.5 transition-all flex items-start gap-2"
                  >
                    <ChevronRight className="w-3.5 h-3.5 shrink-0 mt-0.5 text-violet-500" />
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <>
            {/* YAML mode */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Workflow name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-finetune-workflow"
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-violet-600 transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Workflow YAML
              </label>
              <textarea
                value={yaml}
                onChange={(e) => setYaml(e.target.value)}
                rows={20}
                spellCheck={false}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-xs text-slate-300 font-mono focus:outline-none focus:border-violet-600 resize-y transition-colors"
              />
            </div>
          </>
        )}

        {error && (
          <p className="text-sm text-red-400 bg-red-900/20 border border-red-800/50 rounded-lg px-4 py-3">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || (mode === "prompt" && !prompt.trim())}
          className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 text-white px-6 py-3 rounded-lg text-sm font-medium transition-all"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {mode === "prompt" ? "Generating workflow…" : "Creating…"}
            </>
          ) : (
            <>
              {mode === "prompt" ? <Sparkles className="w-4 h-4" /> : <Code2 className="w-4 h-4" />}
              {mode === "prompt" ? "Generate workflow" : "Create workflow"}
            </>
          )}
        </button>
      </form>
    </div>
  );
}
