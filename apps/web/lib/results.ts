import type { DataPrepMetrics, EvalSummary, ModelRef, RunSummary, WsEvent } from "./types";

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

/** The tab a succeeded run opens on: its eval, else its dataset. Once the user has picked a tab (`picked`) no snapshot takes it back. */
export function resultTab(s: RunSummary, picked: boolean): "eval" | "dataset" | null {
  return picked || s.status !== "succeeded" ? null : evalOf(s) ? "eval" : datasetOf(s) ? "dataset" : null;
}

export interface RunModelRef extends ModelRef {
  label: string;
  expires_at?: string; // vllm-serve endpoints are deleted at expiry
}

/** How a side is named: its label ("base", "tuned"), then its model or endpoint name after `sep` only when that differs. vllm-serve serves
 *  a LoRA adapter as "tuned", so "tuned · tuned" said one word twice (the result panes apply the same rule). */
export const refName = (label: string, model?: string, sep = " · ") => (model && model !== label ? label + sep + model : label);

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

/** One point of the loss chart; valid_loss where the fine-tune reports it (Token Factory checkpoints). */
export interface ProgressPoint { node_id: string; step: number; loss?: number; valid_loss?: number }

/** Node types that train, so a run with none of them has no loss to chart. */
export const TRAINERS = new Set(["tf-finetune", "unsloth-train"]);

type LossSource = { node_id: string; rows?: unknown[]; url?: string };

/** Where each fine-tune node's loss_curve is: its metrics meta, else the file behind download_url (unsloth-train's
 *  train_metrics_json carries no meta, and write_metrics cuts the meta to {truncated: true} above 16 KB). */
export function lossSources(s: RunSummary): LossSource[] {
  return s.nodes.filter((n) => TRAINERS.has(n.type)).flatMap(({ node_id }): LossSource[] => {
    const a = artifact(s, node_id, "metrics_json") ?? artifact(s, node_id, "train_metrics_json");
    const rows = a?.meta?.loss_curve;
    return Array.isArray(rows) ? [{ node_id, rows }] : a?.download_url ? [{ node_id, url: a.download_url }] : [];
  });
}

/** The loss chart's x ticks: 0 and the multiples of a round step (1, 2 or 5 × 10ⁿ) up to `last`, at most `max` steps apart,
 *  so a 60-step curve reads 0, 10 … 60 and the labels never skip unevenly. */
export function stepTicks(last: number, max = 7): number[] {
  const raw = Math.max(last / max, 1); // steps are whole numbers
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  return Array.from({ length: Math.floor(last / step) + 1 }, (_, i) => i * step);
}

const point = (node_id: string, step: number, loss: unknown, valid_loss?: unknown): ProgressPoint => ({
  node_id, step, ...(typeof loss === "number" ? { loss } : {}), ...(typeof valid_loss === "number" ? { valid_loss } : {}),
});

/** The loss chart: each curve's rows (tf-finetune {step, train_loss, valid_loss}; unsloth-train {step, loss}), then live
 *  `progress` events for steps the curves do not have, by step. ponytail: two fine-tune nodes share one line. */
export function lossPoints(curves: { node_id: string; rows: unknown[] }[], events: WsEvent[]): ProgressPoint[] {
  const points = new Map<string, ProgressPoint>();
  const add = (p: ProgressPoint) => {
    const key = `${p.node_id}:${p.step}`;
    if (!points.has(key) && ("loss" in p || "valid_loss" in p)) points.set(key, p);
  };
  for (const { node_id, rows } of curves) {
    for (const r of rows as Record<string, unknown>[]) {
      if (typeof r?.step === "number") add(point(node_id, r.step, r.loss ?? r.train_loss, r.valid_loss));
    }
  }
  for (const e of events) if (e.type === "progress") add(point(e.node_id, e.step, e.loss));
  return [...points.values()].sort((a, b) => a.step - b.step);
}
