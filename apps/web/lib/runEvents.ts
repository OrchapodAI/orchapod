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

/** A run that will change no more (until a retry). */
export const finished = (status: RunStatus) => status === "succeeded" || canRetry(status);

/** How long /agent keeps asking for the report after the run ended: the API writes it in the background (backend-w7). */
export const REPORT_WAIT_MS = 60_000;

/** What the report card does after a poll of GET /agent/runs/{id}/report: stop when the report is `ready`, else poll again,
 *  until the run has been finished for REPORT_WAIT_MS ("gone"). `endedAt` = when a poll first saw the run finished (undefined while it runs). */
export function reportNext(ready: boolean, endedAt: number | undefined, now: number): "done" | "wait" | "gone" {
  return ready ? "done" : endedAt !== undefined && now - endedAt >= REPORT_WAIT_MS ? "gone" : "wait";
}

/** A report starts with its title line, `## <plan name>: <status>` (planner._title); the rest is Markdown, shown as written. */
export function splitReport(md: string): { title: string | null; body: string } {
  const m = md.match(/^## ([^\n]*)\n?([\s\S]*)$/);
  return m ? { title: m[1], body: m[2].trim() } : { title: null, body: md };
}

/** One side of the compare playground. */
export interface CompareSide { text: string; done: boolean; usd: number | null; error?: string }

/** One POST /compare event on its side: a delta appends, done closes it (with a failed stream's error); anything else is ignored. */
export function applyCompareEvent(sides: CompareSide[], e: CompareEvent): CompareSide[] {
  return sides.map((s, i) => i !== e.i ? s
    : "done" in e ? { ...s, done: true, usd: e.usd, error: e.error }
    : typeof e.delta === "string" ? { ...s, text: s.text + e.delta } : s);
}

/** Whether /runs shows `r`. The golden-run link (`/runs?q=<workflow name>`, `linked`) matches that name exactly and hides
 *  runs never started, so "<name> (copy)" workflows stay out; once the box is edited, any substring of the id or name. */
export function runShown(r: { id: string; workflow_name?: string | null; status: string }, search: string, linked: string): boolean {
  if (linked && search === linked) return r.workflow_name === linked && r.status !== "pending";
  const q = search.toLowerCase();
  return r.id.includes(q) || (r.workflow_name ?? "").toLowerCase().includes(q);
}
