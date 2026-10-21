import type {
  Workflow, Run, NodeRun, Artifact, BaseModel, PublicDataset, NodeTypeMeta, NodeType, TrainingMethod,
  DeployRequest, DeployResponse, InferenceEndpoint, ExtendResponse, RegisteredModel, ArtifactListItem,
  AgentPlan, AgentRunOut, AgentReport, Plan, RunSummary,
} from "./types";

export const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  // headers last: spreading init after them would drop Content-Type whenever a caller passes headers
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    let body: unknown = text;
    try { body = JSON.parse(text); } catch { /* not JSON: keep the text */ }
    throw Object.assign(new Error(`${res.status} ${path}: ${text}`), { status: res.status, path, body });
  }
  return res.json() as Promise<T>;
}

/** One readable sentence for a failed call: the /agent page's error state. */
export function explainError(err: unknown): string {
  const { status, path, body } = err as { status?: number; path?: string; body?: unknown };
  if (status === undefined) {
    return err instanceof TypeError ? `Can't reach the Orchapod API at ${BASE}. Is it running?` : String((err as Error)?.message ?? err);
  }
  const raw = (body as { detail?: unknown } | null)?.detail ?? body;
  const detail = Array.isArray(raw) ? raw.map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
    : typeof raw === "string" ? raw : JSON.stringify(raw);
  if (status === 404 && detail === "Not Found") return `The API at ${BASE} has no ${path} route yet (404).`;
  if (status === 402) return `Over budget: ${detail}`;
  if (status === 502) return `Nemotron on Token Factory did not answer after retries (502): ${detail}`;
  if (status === 503) return `The agent is switched off: the kill switch is on or NEBIUS_API_KEY is missing (503: ${detail})`;
  return status === 422 ? detail : `${status} on ${path}: ${detail}`;
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
    /** Re-runs the failed node of a failed or cancelled run, then continues downstream (202). */
    retry(id: string, nodeId: string): Promise<Run> {
      return req(`/runs/${id}/nodes/${encodeURIComponent(nodeId)}/retry`, { method: "POST" });
    },
    summary(id: string): Promise<RunSummary> {
      return req(`/runs/${id}/summary`);
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

  /** Orchapod Agent (docs/contracts.md "Agent API"). */
  agent: {
    plan(intent: string): Promise<AgentPlan> {
      return req("/agent/plan", { method: "POST", body: JSON.stringify({ intent }) });
    },
    run(intent: string, plan: Plan): Promise<AgentRunOut> {
      return req("/agent/run", { method: "POST", body: JSON.stringify({ intent, plan }) });
    },
    report(runId: string): Promise<AgentReport> {
      return req(`/agent/runs/${runId}/report`);
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
