"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState,
  type Node, type Edge, type Connection, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { api } from "@/lib/api";
import type { Workflow, NodeType } from "@/lib/types";
import { OrchaNode, type OrchaNodeData } from "@/components/canvas/OrchaNode";
import { NodePalette } from "@/components/canvas/NodePalette";
import { NodePanel } from "@/components/canvas/NodePanel";
import Link from "next/link";

const nodeTypes = { orchapodNode: OrchaNode };

const DEFAULT_EDGE = {
  animated: false,
  style: { stroke: "#DFE1E6", strokeWidth: 2 },
};

export default function CanvasPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<OrchaNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<Node<OrchaNodeData> | null>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const dropRef = useRef<HTMLDivElement>(null);
  const nodeCounter = useRef(0);

  // Load workflow
  useEffect(() => {
    api.workflows.get(id).then((wf) => {
      setWorkflow(wf);
      const { nodes: n, edges: e } = wf.graph_json;
      // Cast to our typed nodes
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
          resources: { gpu: "1xH100", provider_pref: ["runpod", "vastai"] },
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Create run and navigate to viewer
  async function handleRun() {
    if (!workflow) return;
    setStarting(true);
    setError("");
    try {
      const run = await api.runs.create(id);
      await api.runs.start(run.id);
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setStarting(false);
    }
  }

  if (!workflow) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

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
          {saving ? "Saving…" : "Save draft"}
        </button>
        <button
          onClick={handleRun}
          disabled={starting || nodes.length === 0}
          className="btn btn-sm btn-primary"
        >
          {starting ? "Starting…" : "▶ Run"}
        </button>
      </div>

      {/* Canvas area */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <NodePalette onDragStart={onDragStart} />

        <div ref={dropRef} style={{ flex: 1, minWidth: 0 }} onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
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
              nodeColor={(n) => nodeColor((n.data as OrchaNodeData)?.node_type)}
            />
          </ReactFlow>
        </div>

        {selectedNode && (
          <NodePanel
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            onUpdate={handleNodeUpdate}
          />
        )}
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function nodeColor(type: NodeType): string {
  const map: Record<NodeType, string> = {
    "data-prep":     "oklch(0.65 0.13 200)",
    "unsloth-train": "oklch(0.55 0.18 282)",
    "distill-sft":   "oklch(0.62 0.16 320)",
    "quantize":      "oklch(0.68 0.14 75)",
    "lm-eval":       "oklch(0.62 0.13 162)",
    "vllm-serve":    "oklch(0.55 0.16 25)",
  };
  return map[type] ?? "oklch(0.72 0.008 280)";
}

function defaultInputs(type: NodeType): Record<string, unknown> {
  switch (type) {
    case "data-prep":     return { dataset: "", format: "chatml", train_split: 0.9 };
    case "unsloth-train": return { model: "Qwen/Qwen3-4B-Instruct", train_data: "", eval_data: "", lora_r: 16, lora_alpha: 32, max_steps: 500, learning_rate: 0.0002 };
    case "distill-sft":   return { teacher: "", student_base: "Qwen/Qwen3-1.7B-Instruct", train_data: "", n_synthetic: 5000 };
    case "quantize":      return { model: "", method: "gguf", precision: "q4_k_m" };
    case "lm-eval":       return { models: [], tasks: ["hellaswag", "gsm8k"], judge_eval_set: "" };
    case "vllm-serve":    return { model: "", max_model_len: 8192, keep_alive_min: 60 };
    default:              return {};
  }
}

function buildYamlFromGraph(
  nodes: Node<OrchaNodeData>[],
  edges: Edge[],
  existingYaml: string,
): string {
  // Preserve the existing YAML header (name, version, inputs)
  // then rebuild nodes section from the current graph state.
  // This is a best-effort sync — full round-trip YAML editing is V1.
  const lines = [
    ...existingYaml.split("\n").filter((l) => !l.startsWith("  - id:") && !l.match(/^    (type|needs|inputs|resources):/)),
  ];

  // Find where nodes: starts and truncate there
  const nodesIdx = lines.findIndex((l) => l.trimStart().startsWith("nodes:"));
  const header = nodesIdx >= 0 ? lines.slice(0, nodesIdx + 1) : [...lines, "nodes:"];

  const nodeLines: string[] = [];
  for (const node of nodes) {
    const needs = edges
      .filter((e) => e.target === node.id)
      .map((e) => e.source);

    nodeLines.push(`  - id: ${node.data.label}`);
    nodeLines.push(`    type: ${node.data.node_type}`);
    if (needs.length > 0) {
      nodeLines.push(`    needs: [${needs.join(", ")}]`);
    }
    nodeLines.push("    inputs:");
    for (const [k, v] of Object.entries(node.data.inputs ?? {})) {
      const val = Array.isArray(v) ? JSON.stringify(v) : v;
      nodeLines.push(`      ${k}: ${val}`);
    }
  }

  return [...header, ...nodeLines].join("\n");
}
