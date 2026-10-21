import type { DataPrepMetrics, EvalSummary, ModelRef, RunSummary } from "./types";

// What a run produced, read from GET /runs/{id}/summary (artifact metas come from the DB; no storage fetch).

const artifact = (s: RunSummary, nodeId: string, name: string) => s.artifacts.find((a) => a.node_id === nodeId && a.name === name);

/** judge-eval's result: the numbers from its metrics_json (eval_summary without samples), and the eval_summary file to fetch. */
export function evalOf(s: RunSummary): { stats: Omit<EvalSummary, "samples">; samplesUrl: string | null } | null {
  const file = s.artifacts.find((a) => a.name === "eval_summary");
  const stats = file && artifact(s, file.node_id, "metrics_json")?.meta;
  return stats && "win_rate" in stats ? { stats: stats as Omit<EvalSummary, "samples">, samplesUrl: file.download_url } : null;
}

/** The last data-prep node's cleaned `dataset` (synth's raw one is also called dataset) and its metrics. */
export function datasetOf(s: RunSummary): { downloadUrl: string | null; metrics: Partial<DataPrepMetrics> } | null {
  const prep = s.nodes.filter((n) => n.type === "data-prep").at(-1);
  const file = prep && artifact(s, prep.node_id, "dataset");
  return file ? { downloadUrl: file.download_url, metrics: (artifact(s, file.node_id, "metrics_json")?.meta ?? {}) as Partial<DataPrepMetrics> } : null;
}

export interface RunModelRef extends ModelRef {
  label: string;
  expires_at?: string; // vllm-serve endpoints are deleted at expiry
}

/** Models the playground can compare: the eval's base and tuned first, then every model_ref / base_model_ref artifact. */
export function modelRefsOf(s: RunSummary): RunModelRef[] {
  const stats = evalOf(s)?.stats;
  const found: { label: string; meta: Record<string, unknown> | undefined }[] = [
    { label: "base", meta: stats?.base as Record<string, unknown> | undefined },
    { label: "tuned", meta: stats?.tuned as Record<string, unknown> | undefined },
    ...s.artifacts.filter((a) => a.name === "model_ref" || a.name === "base_model_ref")
      .map((a) => ({ label: `${a.node_id}.${a.name}`, meta: a.meta })),
  ];
  const refs: RunModelRef[] = [];
  for (const { label, meta: m } of found) {
    // api_key_env "" is judge-eval's own llama-server, gone with its container
    if (typeof m?.base_url !== "string" || typeof m.model !== "string" || typeof m.api_key_env !== "string" || !m.api_key_env) continue;
    const expires_at = typeof m.expires_at === "string" ? m.expires_at : undefined;
    const same = refs.find((r) => r.base_url === m.base_url && r.model === m.model);
    if (same) same.expires_at ??= expires_at;
    else refs.push({ label, base_url: m.base_url, model: m.model, api_key_env: m.api_key_env,
                     base_model: typeof m.base_model === "string" ? m.base_model : null, expires_at });
  }
  return refs;
}
