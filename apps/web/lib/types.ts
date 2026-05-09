// ── Workflows ────────────────────────────────────────────────────────────────

export interface Workflow {
  id: string;
  user_id: string;
  name: string;
  yaml: string;
  graph_json: GraphJson;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface GraphJson {
  nodes: ReactFlowNode[];
  edges: ReactFlowEdge[];
}

export interface ReactFlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    node_type: NodeType;
    label: string;
    inputs: Record<string, unknown>;
    resources: Record<string, unknown>;
  };
}

export interface ReactFlowEdge {
  id: string;
  source: string;
  target: string;
}

// ── Runs ─────────────────────────────────────────────────────────────────────

export type RunStatus =
  | "pending"
  | "provisioning_gpu"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type NodeStatus = "pending" | "running" | "succeeded" | "failed";

export interface Run {
  id: string;
  workflow_id: string;
  user_id: string;
  status: RunStatus;
  inputs: Record<string, unknown>;
  cost_usd: number | null;
  started_at: string | null;
  finished_at: string | null;
  gpu_provider: string | null;
  created_at: string;
}

export interface NodeRun {
  id: string;
  run_id: string;
  node_id: string;
  node_type: string;
  status: NodeStatus;
  started_at: string | null;
  finished_at: string | null;
  inputs: Record<string, unknown>;
  outputs: Record<string, string>;
  logs_uri: string | null;
  error: string | null;
}

export interface Artifact {
  id: string;
  node_run_id: string;
  name: string;
  kind: "dataset" | "model" | "metrics" | "log" | "endpoint";
  uri: string;
  size_bytes: number | null;
  meta: Record<string, unknown>;
  created_at: string;
}

// ── Registry ─────────────────────────────────────────────────────────────────

export type NodeType =
  | "data-prep"
  | "unsloth-train"
  | "distill-sft"
  | "quantize"
  | "lm-eval"
  | "vllm-serve";

export interface BaseModel {
  id: string;
  name: string;
  family: string;
  params_b: number;
  context_len: number;
  recommended_gpu: string;
  use_cases: string[];
  hf_url: string;
  requires_hf_token?: boolean;
}

export interface PublicDataset {
  id: string;
  name: string;
  description: string;
  size: string;
  format: string;
  hf_url: string;
  use_cases: string[];
}

export interface NodeTypeMeta {
  description: string;
  runtime: "cpu" | "gpu";
  long_running: boolean;
  inputs_schema: Record<string, unknown>;
  outputs_schema: Record<string, unknown>;
}

// ── WebSocket events ──────────────────────────────────────────────────────────

export type WsEvent =
  | { type: "run_status"; status: RunStatus; error?: string }
  | { type: "node_status"; node_id: string; status: NodeStatus; outputs?: Record<string, string> }
  | { type: "log"; node_id: string; ts: string; level: string; message: string }
  | { type: "progress"; node_id: string; step: number; total?: number; loss?: number }
  | { type: "artifact"; node_id: string; name: string; uri: string; kind: string };
