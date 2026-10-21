import type {
  Workflow, Run, BaseModel, PublicDataset, NodeTypeMeta, NodeType, TrainingMethod,
  DeployRequest, DeployResponse, InferenceEndpoint, RegisteredModel, ArtifactListItem,
  AgentPlan, AgentRunOut, AgentReport, AgentTemplate, Plan, RunSummary, ModelRef, CompareEvent,
} from "./types";

export const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

/** A non-2xx reply as an Error carrying its status, path and parsed body (explainError reads them). */
async function httpError(res: Response, path: string): Promise<Error> {
  const text = await res.text();
  let body: unknown = text;
  try { body = JSON.parse(text); } catch { /* not JSON: keep the text */ }
  return Object.assign(new Error(`${res.status} ${path}: ${text}`), { status: res.status, path, body });
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  // headers last: spreading init after them would drop Content-Type whenever a caller passes headers
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw await httpError(res, path);
  return res.json() as Promise<T>;
}

/** The API sends naive UTC datetimes (no zone); new Date() would read them as local time. */
export const apiDate = (iso: string) => new Date(/(Z|[+-]\d\d:\d\d)$/i.test(iso) ? iso : `${iso}Z`);

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
  // On the agent's routes a 502/503 is the planner or reporter; elsewhere (e.g. /compare) the detail says what failed.
  const agent = path?.startsWith("/agent");
  if (agent && status === 502) return `Nemotron on Token Factory did not answer after retries (502): ${detail}`;
  if (agent && status === 503) return `The agent is switched off: the kill switch is on or NEBIUS_API_KEY is missing (503: ${detail})`;
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
    /** A JSON artifact through its download_url (a 307 to object storage). No headers, so the browser sends no preflight. */
    async content<T>(downloadUrl: string): Promise<T> {
      const res = await fetch(`${BASE}${downloadUrl}`);
      if (!res.ok) throw await httpError(res, downloadUrl);
      return res.json() as Promise<T>;
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
    templates(): Promise<AgentTemplate[]> {
      return req("/agent/templates");
    },
  },

  /** POST /compare: one prompt to two ModelRefs, streamed as SSE. The server resolves each api_key_env; no key is sent. */
  async compare(
    body: { messages: { role: string; content: string }[]; refs: [ModelRef, ModelRef]; max_tokens: number },
    onEvent: (e: CompareEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const res = await fetch(`${BASE}/compare`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    if (!res.ok || !res.body) throw await httpError(res, "/compare");
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      const lines = (buf + (value ?? "")).split("\n");
      buf = done ? "" : lines.pop() ?? ""; // a line split across chunks waits for the rest
      for (const line of lines) {
        const data = line.startsWith("data:") ? line.slice(5).trim() : "";
        if (data.startsWith("{")) onEvent(JSON.parse(data)); // other SSE lines (comments, event:, id:) carry nothing here
      }
      if (done) return;
    }
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
