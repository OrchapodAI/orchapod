import type { CompareEvent, Run, RunStatus, RunSummary, WsEvent } from "./types";

/** What the run page shows: the run (header, cost meter) and its summary (nodes, artifacts). */
export interface RunViewState {
  run: Run;
  summary: RunSummary;
}

/** One WS event applied to the run page (docs/contracts.md "Events"); events it re-fetches for leave it as is. */
export function applyRunEvent(s: RunViewState, e: WsEvent): RunViewState {
  if (e.type === "run_status") return { ...s, run: { ...s.run, status: e.status } };
  if (e.type === "run_cost") return { ...s, run: { ...s.run, cost_usd: e.cost_usd } };
  if (e.type !== "node_status") return s;
  const nodes = s.summary.nodes.map((n) => n.node_id !== e.node_id ? n
    : { ...n, status: e.status, error: e.status === "failed" ? e.error ?? n.error : null });
  return { ...s, summary: { ...s.summary, nodes } };
}

/** The API retries a node only in a stopped run (409 otherwise). */
export const canRetry = (status: RunStatus) => status === "failed" || status === "cancelled";

/** One side of the compare playground. */
export interface CompareSide { text: string; done: boolean; usd: number | null; error?: string }

/** One POST /compare event on its side: a delta appends, done closes it (with a failed stream's error); anything else is ignored. */
export function applyCompareEvent(sides: CompareSide[], e: CompareEvent): CompareSide[] {
  return sides.map((s, i) => i !== e.i ? s
    : "done" in e ? { ...s, done: true, usd: e.usd, error: e.error }
    : typeof e.delta === "string" ? { ...s, text: s.text + e.delta } : s);
}
