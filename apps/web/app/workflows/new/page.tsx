"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { STARTER_YAML } from "@/lib/workflowYaml";

type Mode = "prompt" | "yaml";

const EXAMPLE_PROMPTS = [  // the Agent's canonical intents (docs/agent_knowledge.md); the docs one is over a visitor's cap
  "Generate synthetic data of movie likes, shares and subscribes",
  "Quantize a model which is an expert in maths",
  "Distill a Nebius docs specialist: fine-tune NVIDIA Nemotron Nano 8B on the Nebius AI Cloud and Token Factory docs",
];

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
        if (!name.trim()) { setError("Please enter a workflow name."); return; }
        workflow = await api.workflows.create({ name: name.trim(), yaml });
      }
      router.push(`/canvas/${workflow.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 12px", borderRadius: 6,
    border: "1px solid var(--line-2)", background: "var(--surface)",
    fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--ink-1)",
    outline: "none", transition: "border-color .12s",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Topbar */}
      <div className="op-topbar">
        <div className="op-crumbs">
          <Link href="/workflows" style={{ textDecoration: "none", color: "var(--ink-3)" }}>Workflows</Link>
          <span className="sep">/</span>
          <span className="here">New workflow</span>
        </div>
        <div className="spacer" />
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "40px 24px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em", marginBottom: 4 }}>New workflow</h1>
          <p className="muted" style={{ fontSize: 13.5, marginBottom: 28 }}>
            Describe your goal in plain English, or write YAML directly.
          </p>

          {/* Mode tabs */}
          <div className="row" style={{ borderBottom: "1px solid var(--line)", marginBottom: 28, gap: 4 }}>
            {(["prompt", "yaml"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                style={{
                  padding: "10px 12px", border: "none", background: "transparent",
                  borderBottom: mode === m ? "2px solid var(--brand)" : "2px solid transparent",
                  color: mode === m ? "var(--brand-ink)" : "var(--ink-3)",
                  fontWeight: mode === m ? 500 : 400, cursor: "pointer",
                  fontFamily: "var(--font-ui)", fontSize: 13,
                }}
              >
                {m === "prompt" ? "✦ AI prompt" : "{ } YAML"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {mode === "prompt" ? (
              <>
                <div>
                  <label style={{ display: "block", fontSize: 12, fontWeight: 500, color: "var(--ink-2)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Describe your workflow
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={5}
                    required
                    placeholder={`e.g. ${EXAMPLE_PROMPTS[0]}`}
                    style={{ ...inputStyle, resize: "none" }}
                  />
                </div>

                <div>
                  <p style={{ fontSize: 10.5, fontWeight: 500, color: "var(--ink-3)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>Examples</p>
                  <div className="col" style={{ gap: 6 }}>
                    {EXAMPLE_PROMPTS.map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        onClick={() => setPrompt(ex)}
                        style={{
                          textAlign: "left", fontSize: 12.5, color: "var(--ink-2)",
                          background: "var(--bg-2)", border: "1px solid var(--line)",
                          borderRadius: 6, padding: "10px 12px", cursor: "pointer",
                          display: "flex", alignItems: "flex-start", gap: 8,
                          fontFamily: "var(--font-ui)",
                        }}
                      >
                        <span style={{ color: "var(--brand)" }}>→</span>
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label style={{ display: "block", fontSize: 12, fontWeight: 500, color: "var(--ink-2)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Workflow name
                  </label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="synthetic-movie-events"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 12, fontWeight: 500, color: "var(--ink-2)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Workflow YAML
                  </label>
                  <textarea
                    value={yaml}
                    onChange={(e) => setYaml(e.target.value)}
                    rows={22}
                    spellCheck={false}
                    style={{
                      ...inputStyle, resize: "vertical",
                      fontFamily: "var(--font-mono)", fontSize: 12,
                      background: "var(--code-bg)", color: "var(--code-text)",
                      border: "1px solid var(--code-line)",
                    }}
                  />
                </div>
              </>
            )}

            {error && (
              <div style={{
                fontSize: 13, color: "var(--rose-ink)", background: "var(--rose-soft)",
                border: "1px solid var(--rose)", borderRadius: 6, padding: "10px 14px",
              }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || (mode === "prompt" && !prompt.trim())}
              className="btn btn-primary"
              style={{ width: "100%", justifyContent: "center", padding: "10px 16px", fontSize: 14 }}
            >
              {loading
                ? (mode === "prompt" ? "Generating workflow…" : "Creating…")
                : (mode === "prompt" ? "✦ Generate workflow" : "Create workflow")}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
