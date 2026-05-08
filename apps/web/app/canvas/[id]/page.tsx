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
import {
  Save, Play, ArrowLeft, Loader2, ChevronRight, AlertCircle,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";

const nodeTypes = { orchapodNode: OrchaNode };

const DEFAULT_EDGE = {
  animated: false,
  style: { stroke: "#475569", strokeWidth: 2 },
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
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/80 backdrop-blur shrink-0 gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/workflows" className="p-1.5 rounded-md text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-slate-100 truncate">{workflow.name}</h1>
            <p className="text-[11px] text-slate-500">v{workflow.version} · {nodes.length} nodes</p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {error && (
            <p className="flex items-center gap-1.5 text-xs text-red-400">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-slate-300 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>
          <button
            onClick={handleRun}
            disabled={starting || nodes.length === 0}
            className={clsx(
              "flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors",
              "bg-violet-600 hover:bg-violet-500 text-white disabled:bg-slate-800 disabled:text-slate-600"
            )}
          >
            {starting
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Play className="w-3.5 h-3.5 fill-current" />}
            Run
          </button>
        </div>
      </div>

      {/* Canvas area */}
      <div className="flex flex-1 min-h-0">
        <NodePalette onDragStart={onDragStart} />

        <div ref={dropRef} className="flex-1 min-w-0" onDrop={onDrop} onDragOver={onDragOver}>
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
            className="bg-slate-950"
            deleteKeyCode="Backspace"
          >
            <Background color="#1e293b" gap={20} size={1} />
            <Controls className="!bottom-4 !left-4" />
            <MiniMap
              nodeColor={(n) => nodeColor((n.data as OrchaNodeData)?.node_type)}
              className="!bottom-4 !right-4"
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
    "data-prep":     "#38bdf8",
    "unsloth-train": "#a78bfa",
    "distill-sft":   "#e879f9",
    "quantize":      "#fbbf24",
    "lm-eval":       "#34d399",
    "vllm-serve":    "#fb7185",
  };
  return map[type] ?? "#64748b";
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
