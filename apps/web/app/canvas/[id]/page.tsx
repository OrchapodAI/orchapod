"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState,
  type Node, type Edge, type Connection, type ReactFlowInstance, type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { api } from "@/lib/api";
import type { Run, Workflow, NodeType } from "@/lib/types";
import { OrchaNode, NODE_META, type OrchaNodeData } from "@/components/canvas/OrchaNode";
import { NodePalette } from "@/components/canvas/NodePalette";
import { NodePanel } from "@/components/canvas/NodePanel";
import Link from "next/link";
import { buildYamlFromGraph } from "@/lib/workflowYaml";
import { formDefaults } from "@/lib/nodeForms";

const nodeTypes: NodeTypes = { orchapodNode: OrchaNode as NodeTypes[string] };

const DEFAULT_EDGE = {
  animated: false,
  style: { stroke: "#DFE1E6", strokeWidth: 2 },
};

type CostQuote = {
  provider: string;
  price_per_hour?: number;
  available?: boolean;
  gpu_type?: string;
  note?: string;
  error?: string;
};
type NodeEstimate = { node_id: string; node_type: string; quotes: CostQuote[] };

export default function CanvasPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<OrchaNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<Node<OrchaNodeData> | null>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance<Node<OrchaNodeData>, Edge> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const dropRef = useRef<HTMLDivElement>(null);
  const nodeCounter = useRef(0);

  // Cost-estimate modal state
  const [pendingRun, setPendingRun] = useState<Run | null>(null);
  const [costEstimates, setCostEstimates] = useState<NodeEstimate[]>([]);
  const [loadingEstimate, setLoadingEstimate] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // Load workflow
  useEffect(() => {
    api.workflows.get(id).then((wf) => {
      setWorkflow(wf);
      const { nodes: n, edges: e } = wf.graph_json;
      setNodes(n.map((node) => ({ ...node, type: "orchapodNode" })) as Node<OrchaNodeData>[]);
      setEdges(e.map((edge) => ({ ...edge, ...DEFAULT_EDGE })));
    });
  }, [id]);

  // Connect edges
  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, ...DEFAULT_EDGE }, eds)),
    [setEdges]
  );

  // Node selection
  const onNodeClick = useCallback((_: unknown, node: Node<OrchaNodeData>) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => setSelectedNode(null), []);

  // Update node data from panel
  function handleNodeUpdate(nodeId: string, data: Partial<OrchaNodeData>) {
    setNodes((nds) =>
      nds.map((n) => n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n)
    );
    if (selectedNode?.id === nodeId) {
      setSelectedNode((prev) => prev ? { ...prev, data: { ...prev.data, ...data } } : prev);
    }
  }

  // Drag-from-palette
  function onDragStart(e: React.DragEvent, type: NodeType) {
    e.dataTransfer.setData("application/orchapod-node-type", type);
    e.dataTransfer.effectAllowed = "move";
  }

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const type = e.dataTransfer.getData("application/orchapod-node-type") as NodeType;
      if (!type || !rfInstance) return;

      const bounds = dropRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const position = rfInstance.screenToFlowPosition({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      });

      nodeCounter.current += 1;
      const nodeId = `${type}_${nodeCounter.current}`;
      const newNode: Node<OrchaNodeData> = {
        id: nodeId,
        type: "orchapodNode",
        position,
        data: {
          node_type: type,
          label: nodeId,
          inputs: defaultInputs(type),
          resources: {},
        },
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [rfInstance, setNodes]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  // Save YAML (regenerated from current node/edge state)
  async function handleSave() {
    if (!workflow) return;
    setSaving(true);
    setError("");
    try {
      const yaml = buildYamlFromGraph(nodes, edges, workflow.yaml);
      await api.workflows.update(id, { yaml });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Step 1: create run and show cost estimate modal
  async function handleRun() {
    if (!workflow) return;
    setStarting(true);
    setError("");
    try {
      const run = await api.runs.create(id);
      setPendingRun(run);
      setLoadingEstimate(true);
      const estimate = await api.runs.costEstimate(run.id);
      setCostEstimates(estimate.nodes as NodeEstimate[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create run");
      setPendingRun(null);
    } finally {
      setStarting(false);
      setLoadingEstimate(false);
    }
  }

  // Step 2: user confirmed — start the pending run
  async function handleConfirmRun() {
    if (!pendingRun) return;
    setConfirming(true);
    try {
      await api.runs.start(pendingRun.id);
      router.push(`/runs/${pendingRun.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setPendingRun(null);
      setCostEstimates([]);
    } finally {
      setConfirming(false);
    }
  }

  // Step 2 alt: user cancelled — leave the pending run, just close modal
  function handleCancelRun() {
    setPendingRun(null);
    setCostEstimates([]);
  }

  if (!workflow) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  const showModal = !!pendingRun;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Topbar */}
      <div className="op-topbar">
        <Link href="/workflows" className="btn btn-sm btn-ghost" style={{ textDecoration: "none" }}>← Workflows</Link>
        <div className="op-crumbs">
          <span className="here">{workflow.name}</span>
        </div>
        <span className="muted mono" style={{ fontSize: 11 }}>v{workflow.version} · {nodes.length} nodes</span>
        <div className="spacer" />
        {error && <span className="muted" style={{ fontSize: 12, color: "var(--rose)" }}>{error}</span>}
        <button onClick={handleSave} disabled={saving} className="btn btn-sm">
          {saving ? "Saving…" : saved ? "Saved ✓" : "Save draft"}
        </button>
        <button
          onClick={handleRun}
          disabled={starting || nodes.length === 0 || showModal}
          className="btn btn-sm btn-primary"
        >
          {starting ? "Estimating…" : "▶ Run"}
        </button>
      </div>

      {/* Canvas area */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <NodePalette onDragStart={onDragStart} />

        <div ref={dropRef} style={{ flex: 1, minWidth: 0 }} onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow<Node<OrchaNodeData>, Edge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onInit={setRfInstance}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            style={{ background: "var(--bg-2)" }}
            deleteKeyCode="Backspace"
          >
            <Background color="oklch(0.86 0.010 280)" gap={20} size={1} />
            <Controls />
            <MiniMap
              nodeColor={(n) => NODE_META[(n.data as OrchaNodeData)?.node_type]?.accent ?? "#97A0AF"}
            />
          </ReactFlow>
        </div>

        {selectedNode && (
          <NodePanel
            key={selectedNode.id}
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            onUpdate={handleNodeUpdate}
          />
        )}
      </div>

      {/* Cost estimate modal */}
      {showModal && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 50,
          background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div className="card" style={{
            width: 540, maxWidth: "90vw", padding: 24,
            display: "flex", flexDirection: "column", gap: 16,
          }}>
            <div>
              <p style={{ fontSize: 15, fontWeight: 600, color: "var(--ink-1)" }}>Cost estimate</p>
              <p className="muted" style={{ fontSize: 12.5, marginTop: 3 }}>
                GPU quotes for each node in this run. Actual cost depends on runtime.
              </p>
            </div>

            {loadingEstimate ? (
              <p className="muted" style={{ fontSize: 13 }}>Fetching quotes…</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {costEstimates.map((ne) => {
                  const best = ne.quotes.find((q) => q.available && !q.error) ?? ne.quotes[0];
                  return (
                    <div key={ne.node_id} style={{
                      padding: "10px 12px",
                      background: "var(--bg-2)",
                      border: "1px solid var(--line)",
                      borderRadius: 6,
                    }}>
                      <div className="row" style={{ gap: 10, alignItems: "center" }}>
                        <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--ink-1)", flex: 1 }}>
                          {ne.node_id}
                        </span>
                        <span className="pill" style={{ fontSize: 10 }}>{ne.node_type}</span>
                      </div>
                      {best && (
                        <div className="row" style={{ gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                          {best.error ? (
                            <span className="muted" style={{ fontSize: 11 }}>No quote available</span>
                          ) : (
                            <>
                              <span className="muted" style={{ fontSize: 11 }}>{best.provider}</span>
                              {best.gpu_type && (
                                <span className="muted" style={{ fontSize: 11 }}>· {best.gpu_type}</span>
                              )}
                              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--brand)" }}>
                                ${best.price_per_hour?.toFixed(2)}/hr
                              </span>
                              {!best.available && (
                                <span style={{ fontSize: 10, color: "var(--rose)", fontWeight: 500 }}>unavailable</span>
                              )}
                            </>
                          )}
                        </div>
                      )}
                      {/* Other provider quotes */}
                      {ne.quotes.length > 1 && (
                        <div className="row" style={{ gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                          {ne.quotes.slice(1).map((q) => !q.error && (
                            <span key={q.provider} className="muted" style={{ fontSize: 10 }}>
                              {q.provider} ${q.price_per_hour?.toFixed(2)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {costEstimates.length === 0 && (
                  <p className="muted" style={{ fontSize: 13 }}>No GPU nodes in this workflow.</p>
                )}
              </div>
            )}

            <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={handleCancelRun}
                className="btn btn-sm"
                disabled={confirming}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmRun}
                disabled={confirming || loadingEstimate}
                className="btn btn-sm btn-primary"
              >
                {confirming ? "Starting…" : "Confirm & Start"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function defaultInputs(type: NodeType): Record<string, unknown> {
  const fromForm = formDefaults(type);
  if (fromForm) return fromForm;
  switch (type) {
    case "hf-download":         return { model_id: "", revision: "main", ignore_patterns: [] };
    case "data-prep":           return { dataset: "", format: "chatml", train_split: 0.9 };
    case "synth-distilabel":    return { pipeline_template: "self-instruct", teacher_kind: "nebius", teacher_model: "nvidia/nemotron-3-super-120b-a12b", n_samples: 1000, temperature: 0.8, max_tokens: 512 };
    case "unsloth-train":       return { model: "Qwen/Qwen3-4B-Instruct", train_data: "", eval_data: "", lora_r: 16, lora_alpha: 32, max_steps: 500, learning_rate: 0.0002 };
    case "distill-sft":         return { teacher: "", student_base: "Qwen/Qwen3-1.7B-Instruct", train_data: "", n_synthetic: 5000 };
    case "quantize":            return { model: "", method: "gguf", precision: "q4_k_m" };
    case "lm-eval":             return { models: [], tasks: ["hellaswag", "gsm8k"], judge_eval_set: "" };
    case "vllm-serve":          return { model: "", max_model_len: 8192, keep_alive_min: 60 };
    default:                    return {};
  }
}
