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
  workflow_id: string | null;
  /** null once the workflow is gone; /runs names and filters runs by it (the golden-run link). */
  workflow_name: string | null;
  user_id: string;
  status: RunStatus;
  inputs: Record<string, unknown>;
  cost_usd: number | null;
  started_at: string | null;
  finished_at: string | null;
  gpu_provider: string | null;
  created_at: string;
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

/** GET /runs/{id}/summary (docs/contracts.md "Run control API"). */
export interface RunSummary {
  run_id: string;
  status: RunStatus;
  cost_usd: number;
  error: string | null;
  nodes: { node_id: string; type: string; status: NodeStatus; usd: number; error: string | null;
           started_at: string | null; finished_at: string | null;
           /** Where the node ran (backend-w9): "local-docker", "nebius" or null. */
           provider?: string | null;
           /** The Nebius Job or Endpoint behind it; `state` is read live, and only while the node runs. */
           resource?: { kind: "job" | "endpoint"; id: string; state: string | null } | null }[];
  /** download_url is an API path (/artifacts/{id}/download) for r2:// artifacts, else null. */
  artifacts: { id: string; node_id: string; name: string; kind: Artifact["kind"]; uri: string;
               download_url: string | null; meta: Record<string, unknown> }[];
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

// ── Results (docs/contracts.md "ML nodes" and "data-prep") ────────────────────

/** An OpenAI-compatible target. api_key_env names an env var on the server; no key ever reaches the browser. */
export interface ModelRef {
  base_url: string;
  model: string;
  api_key_env: string;
  base_model: string | null;
}

/** One judged test row, from tuned's side: a win needs both answer orders to pick tuned. */
export interface Verdict {
  i: number;
  question: string;
  reference: string;
  context?: string | null;
  source_url?: string | null;
  base: string;
  tuned: string;
  base_correct: boolean | null;
  tuned_correct: boolean | null;
  verdict: "win" | "tie" | "loss" | null;
  judgments: { order: "tuned_first" | "base_first"; winner: "tuned" | "base" | "tie"; reasoning: string }[];
  error: string | null;
}

/** judge-eval's eval_summary; its metrics_json is the same without `samples`. */
export interface EvalSummary {
  n: number;
  judged: number;
  wins: number;
  ties: number;
  losses: number;
  errors: number;
  win_rate: number | null;
  consistency: number | null;
  exact_match: { base: number; tuned: number } | null;
  base: ModelRef;
  tuned: ModelRef;
  judge_model: string;
  decoding: { temperature: number; max_tokens: number };
  stub: boolean;
  samples: Verdict[];
}

/** data-prep's metrics_json; `fields` only for structured rows (min/max for numeric and ISO-8601 fields). */
export interface DataPrepMetrics {
  total: number;
  train: number;
  eval: number;
  test: number;
  skipped: number;
  exact_dupes: number;
  near_dupes: number;
  quality_dropped: number;
  stub?: boolean;
  fields?: Record<string, { distinct: number; nulls: number; top: [unknown, number][]; min?: unknown; max?: unknown }>;
}

/** POST /compare streams these per side i: deltas, then one done (with `error` when the stream failed mid-answer). */
export type CompareEvent =
  | { i: 0 | 1; delta: string }
  | { i: 0 | 1; done: true; usd: number | null; error?: string };

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

/** GET /agent/templates: the three canonical intents with ready plans; one-click Run posts one to /agent/run. */
export interface AgentTemplate {
  slug: string;
  title: string;
  intent: string;
  rationale: string;
  plan: Plan;
  estimate: Estimate;
  /** "Run it yourself": the same plan at reduced scale, sized for the anonymous caps; one-click Run posts it. */
  reduced?: { plan: Plan; estimate: Estimate };
  /** false: the reduced estimate is above this caller's per-run cap, so Run stays disabled. Undefined = runnable. */
  fits?: boolean;
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

/** One log line: as GET /runs/{id}/logs returns it, and as a `log` event carries it. */
export interface LogLine {
  ts: string;
  level: string;
  node_id: string;
  message: string;
}

// ── WebSocket events ──────────────────────────────────────────────────────────

export type WsEvent =
  | { type: "run_status"; status: RunStatus; error?: string }
  | { type: "run_cost"; cost_usd: number }
  | { type: "node_status"; node_id: string; status: NodeStatus; outputs?: Record<string, string>; error?: string }
  | { type: "log"; node_id: string; ts: string; level: string; message: string }
  | { type: "progress"; node_id: string; step: number; total?: number; loss?: number }
  | { type: "artifact"; node_id: string; name: string; uri: string; kind: string; expires_at?: string }
  | { type: "endpoint_expiry"; node_run_id: string; expires_at?: string; minutes_remaining: number };
