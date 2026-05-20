import type {
  Workflow, Run, NodeRun, Artifact, BaseModel, PublicDataset, NodeTypeMeta, NodeType, TrainingMethod,
  DeployRequest, DeployResponse, InferenceEndpoint, ExtendResponse, RegisteredModel, ArtifactListItem,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${path}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Workflows ─────────────────────────────────────────────────────────────────

export const api = {
  workflows: {
    list(): Promise<Workflow[]> {
      return req("/workflows");
    },
    get(id: string): Promise<Workflow> {
      return req(`/workflows/${id}`);
    },
    create(body: { name: string; yaml: string }): Promise<Workflow> {
      return req("/workflows", { method: "POST", body: JSON.stringify(body) });
    },
    fromPrompt(prompt: string): Promise<Workflow> {
      return req("/workflows/from-prompt", { method: "POST", body: JSON.stringify({ prompt }) });
    },
    update(id: string, body: { name?: string; yaml?: string }): Promise<Workflow> {
      return req(`/workflows/${id}`, { method: "PUT", body: JSON.stringify(body) });
    },
    delete(id: string): Promise<void> {
      return req(`/workflows/${id}`, { method: "DELETE" });
    },
  },

  runs: {
    list(workflowId?: string): Promise<Run[]> {
      const qs = workflowId ? `?workflow_id=${workflowId}` : "";
      return req(`/runs${qs}`);
    },
    get(id: string): Promise<Run> {
      return req(`/runs/${id}`);
    },
    create(workflowId: string, inputs: Record<string, unknown> = {}): Promise<Run> {
      return req("/runs", {
        method: "POST",
        body: JSON.stringify({ workflow_id: workflowId, inputs }),
      });
    },
    start(id: string): Promise<Run> {
      return req(`/runs/${id}/start`, { method: "POST" });
    },
    cancel(id: string): Promise<Run> {
      return req(`/runs/${id}/cancel`, { method: "POST" });
    },
    nodes(id: string): Promise<NodeRun[]> {
      return req(`/runs/${id}/nodes`);
    },
    artifacts(id: string): Promise<Artifact[]> {
      return req(`/runs/${id}/artifacts`);
    },
    costEstimate(id: string): Promise<{ nodes: { node_id: string; node_type: NodeType; quotes: unknown[] }[] }> {
      return req(`/runs/${id}/cost-estimate`);
    },
  },

  inference: {
    deploy(body: DeployRequest): Promise<DeployResponse> {
      return req("/inference/deploy", { method: "POST", body: JSON.stringify(body) });
    },
    endpoints(): Promise<InferenceEndpoint[]> {
      return req("/inference/endpoints");
    },
    /** Extend a live endpoint by extend_min (default 60). */
    extend(runId: string, extendMin = 60): Promise<ExtendResponse> {
      return req(`/inference/extend/${runId}`, {
        method: "POST",
        body:   JSON.stringify({ extend_min: extendMin }),
      });
    },
    /** Dry-run: returns cost estimate without changing anything. */
    extendPreview(runId: string, extendMin = 60): Promise<ExtendResponse> {
      return req(`/inference/extend/${runId}?preview=1`, {
        method: "POST",
        body:   JSON.stringify({ extend_min: extendMin }),
      });
    },
  },

  /** Trained/quantized models auto-registered from runs. */
  models: {
    list(params?: { format?: string; base_model?: string; tag?: string }): Promise<RegisteredModel[]> {
      const qs = params
        ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]).toString()
        : "";
      return req(`/models${qs}`);
    },
    get(id: string): Promise<RegisteredModel> {
      return req(`/models/${id}`);
    },
  },

  /** Global artifact browser. */
  artifacts: {
    list(params?: { kind?: string; limit?: number }): Promise<ArtifactListItem[]> {
      const qs = params
        ? "?" + new URLSearchParams(
            Object.entries(params)
              .filter(([, v]) => v != null)
              .map(([k, v]) => [k, String(v)])
          ).toString()
        : "";
      return req(`/artifacts${qs}`);
    },
  },

  registry: {
    models(): Promise<{ models: BaseModel[] }> {
      return req("/registry/models");
    },
    datasets(): Promise<{ datasets: PublicDataset[] }> {
      return req("/registry/datasets");
    },
    nodeTypes(): Promise<{ node_types: Record<NodeType, NodeTypeMeta> }> {
      return req("/registry/node-types");
    },
    methods(): Promise<{ methods: TrainingMethod[] }> {
      return req("/registry/methods");
    },
  },
};
