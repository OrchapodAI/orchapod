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
  | "hf-download"
  | "hf-import"
  | "file-upload"
  | "s3-import"
  | "data-prep"
  | "auto-label-cleanlab"
  | "synth-distilabel"
  | "unsloth-train"
  | "distill-sft"
  | "quantize"
  | "lm-eval"
  | "vllm-serve"
  | "web-research"
  | "tf-finetune"
  | "tf-deploy"
  | "judge-eval";

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

export interface TrainingMethod {
  method_id: string;
  display_name: string;
  framework: string;
  container: string;
  description: string;
  runtime: "cpu" | "gpu";
  default_hyperparams: Record<string, unknown>;
  supported_models: string[];
}

// ── Inference ─────────────────────────────────────────────────────────────────

export type InferenceMode = "serve" | "quantize-serve" | "quantize-gguf";

export interface DeployRequest {
  model: string;
  mode: InferenceMode;
  gpu?: string;
  max_model_len?: number;
  keep_alive_min?: number;
  precision?: "q4_k_m" | "q5_k_m" | "q8_0";
  served_model_name?: string;
  hf_token?: string;
}

export interface DeployResponse {
  run_id: string;
  workflow_id: string;
  status: string;
  mode: InferenceMode;
  model: string;
}

export interface InferenceEndpoint {
  run_id: string;
  workflow_name: string;
  model: string;
  endpoint_url: string | null;
  status: string;
  started_at: string | null;
  keep_alive_min: number | null;
  gpu_provider: string | null;
}

// ── Registered models (model_registry) ───────────────────────────────────────

export interface RegisteredModel {
  id:          string;
  name:        string;
  base_model:  string;
  format:      "hf" | "awq" | "gguf";
  uri:         string;
  tags:        string[];
  description: string | null;
  created_at:  string;
}

// ── Global artifact list ──────────────────────────────────────────────────────

export interface ArtifactListItem {
  id:            string;
  run_id:        string;
  node_run_id:   string;
  workflow_id:   string | null;
  workflow_name: string | null;
  node_id:       string;
  name:          string;
  kind:          "dataset" | "model" | "metrics" | "log" | "endpoint";
  uri:           string;
  size_bytes:    number | null;
  meta:          Record<string, unknown>;
  created_at:    string;
}

// ── Extend endpoint (KAN-30) ──────────────────────────────────────────────────

export interface ExtendResponse {
  run_id:            string;
  expires_at:        string;   // ISO-8601
  extend_min:        number;
  cost_estimate_usd: number;
}

// ── Agent (docs/contracts.md "Agent API") ────────────────────────────────────

export interface PlanNode {
  id: string;
  type: NodeType;
  needs?: string[];
  inputs?: Record<string, unknown>;
}

export interface Plan {
  name: string;
  nodes: PlanNode[];
}

export interface Estimate {
  usd: number;
  minutes: number;
  by_node: Record<string, { usd: number; minutes: number }>;
}

export interface AgentPlan {
  plan: Plan;
  rationale: string;
  estimate: Estimate;
  warnings: string[];
  errors: string[];
}

export interface AgentRunOut {
  run_id: string;
  workflow_id: string;
  estimate: Estimate;
}

export interface AgentReport {
  run_id: string;
  status: RunStatus;
  cost_usd: number | null;
  error: string | null;
  intent: string;
  estimate: Estimate;
  ready: boolean;
  markdown: string | null;
}

// ── WebSocket events ──────────────────────────────────────────────────────────

export type WsEvent =
  | { type: "run_status"; status: RunStatus; error?: string }
  | { type: "run_cost"; cost_usd: number }
  | { type: "node_status"; node_id: string; status: NodeStatus; outputs?: Record<string, string> }
  | { type: "log"; node_id: string; ts: string; level: string; message: string }
  | { type: "progress"; node_id: string; step: number; total?: number; loss?: number }
  | { type: "artifact"; node_id: string; name: string; uri: string; kind: string; expires_at?: string }
  | { type: "endpoint_expiry"; node_run_id: string; expires_at?: string; minutes_remaining: number };
