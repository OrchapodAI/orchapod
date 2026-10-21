// Web unit tests. Run from the repo root: node --test "tests/web/*.test.ts"
// (Node >= 22.18 strips the types itself, so there is nothing to install.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { yamlValue, buildYamlFromGraph, planYaml } from "../../apps/web/lib/workflowYaml.ts";
import { api, apiDate, explainError } from "../../apps/web/lib/api.ts";
import { applyRunEvent, canRetry } from "../../apps/web/lib/runEvents.ts";
import { defaultInputs, NODE_FORMS } from "../../apps/web/lib/nodeForms.ts";
import { datasetOf, evalOf, modelRefsOf } from "../../apps/web/lib/results.ts";

const node = (id: string, node_type: string, inputs: Record<string, unknown>) =>
  ({ id, position: { x: 0, y: 0 }, data: { label: id, node_type, inputs, resources: {} } }) as never;

test("object and list inputs are written as JSON (R13)", () => {
  const rowSchema = { type: "object", properties: { action: { enum: ["like", "share"] } } };
  assert.equal(yamlValue(rowSchema), JSON.stringify(rowSchema));
  assert.equal(yamlValue({}), "{}");
  assert.equal(yamlValue(["Fair Housing Act", "RESPA"]), '["Fair Housing Act","RESPA"]');
});

test("strings a plain YAML scalar would misread are JSON-quoted; the rest stay plain", () => {
  // Plain YAML cannot start with a flow indicator or a quote: LLM text such as "[draft] …" reaches planYaml.
  for (const s of ["", "Audience: brokers", "see #3", "two\nlines", " padded", "*bold*", "- item",
    "[draft] notes", "{x} y", '"quoted" lead', "'single' lead", ", comma", "] x", "} x"]) {
    assert.equal(yamlValue(s), JSON.stringify(s), s);
  }
  for (const s of ["16", "meta-llama/Llama-3.1-8B-Instruct", "${{ nodes.prep.outputs.train_jsonl }}", "https://a.io/x#y", "test[:50]", "a, b"]) {
    assert.equal(yamlValue(s), s, s);
  }
  assert.equal(yamlValue(0.9), "0.9");
  assert.equal(yamlValue(false), "false");
});

test("buildYamlFromGraph keeps the header, takes needs from edges and writes objects as JSON", () => {
  const yaml = buildYamlFromGraph(
    [
      node("synth", "synth-distilabel", { row_schema: { type: "object" }, n_samples: 100 }),
      node("prep", "data-prep", { dataset: "${{ nodes.synth.outputs.dataset }}" }),
    ],
    [{ id: "synth->prep", source: "synth", target: "prep" }],
    "name: movies\nversion: 1\nnodes:\n  - id: old\n    type: data-prep\n",
  );
  assert.equal(yaml, [
    "name: movies", "version: 1", "nodes:",
    "  - id: synth", "    type: synth-distilabel", "    inputs:",
    '      row_schema: {"type":"object"}', "      n_samples: 100",
    "  - id: prep", "    type: data-prep", "    needs: [synth]", "    inputs:",
    "      dataset: ${{ nodes.synth.outputs.dataset }}",
  ].join("\n"));
});

test("planYaml turns an agent plan into workflow YAML; empty inputs stay a mapping", () => {
  const yaml = planYaml({
    name: "movie-events",
    nodes: [
      { id: "synth", type: "synth-distilabel", needs: [], inputs: {} },
      { id: "prep", type: "data-prep", needs: ["synth"], inputs: { format: "structured" } },
    ],
  });
  assert.equal(yaml, [
    "name: movie-events", "nodes:",
    "  - id: synth", "    type: synth-distilabel", "    inputs: {}",
    "  - id: prep", "    type: data-prep", "    needs: [synth]", "    inputs:", "      format: structured",
  ].join("\n"));
});

test("a failed call rejects with its status, path and parsed body", async () => {
  globalThis.fetch = async () => new Response('{"detail":"Not Found"}', { status: 404 });
  await assert.rejects(api.agent.plan("movie likes"), (e: { status: number; path: string; body: { detail: string } }) =>
    e.status === 404 && e.path === "/agent/plan" && e.body.detail === "Not Found");
});

test("explainError turns each agent failure into a readable sentence", () => {
  const http = (status: number, path: string, body: unknown) => Object.assign(new Error(String(status)), { status, path, body });
  assert.equal(explainError(new TypeError("Failed to fetch")), "Can't reach the Orchapod API at http://localhost:8001. Is it running?");
  assert.equal(explainError(http(404, "/agent/plan", { detail: "Not Found" })), "The API at http://localhost:8001 has no /agent/plan route yet (404).");
  assert.equal(explainError(http(404, "/agent/runs/r1/report", { detail: "not an agent run" })), "404 on /agent/runs/r1/report: not an agent run");
  assert.equal(explainError(http(422, "/agent/plan", { detail: [{ msg: "String should have at most 2000 characters" }] })), "String should have at most 2000 characters");
  assert.match(explainError(http(402, "/agent/run", { detail: "day cap $15 reached" })), /^Over budget: day cap \$15 reached/);
  assert.match(explainError(http(502, "/agent/plan", { detail: "token_factory server 503" })), /Token Factory/);
  assert.match(explainError(http(503, "/agent/plan", { detail: "kill switch" })), /kill switch/);
  assert.equal(explainError(http(500, "/agent/plan", "Internal Server Error")), "500 on /agent/plan: Internal Server Error");
});

test("the run page reads GET /runs/{id}/summary and retries with POST /runs/{id}/nodes/{node_id}/retry", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return new Response("{}");
  };
  await api.runs.summary("r1");
  await api.runs.retry("r1", "prep");
  assert.deepEqual(calls, ["GET http://localhost:8001/runs/r1/summary", "POST http://localhost:8001/runs/r1/nodes/prep/retry"]);
});

test("run events drive the cost meter, the run status and each node's status and verbatim error", () => {
  const view = {
    run: { status: "running", cost_usd: null },
    summary: { nodes: [{ node_id: "prep", status: "running", error: null }, { node_id: "train", status: "pending", error: null }] },
  } as never;
  assert.equal(applyRunEvent(view, { type: "run_cost", cost_usd: 0.0123 }).run.cost_usd, 0.0123);
  assert.equal(applyRunEvent(view, { type: "run_status", status: "failed", error: "x" }).run.status, "failed");
  const error = 'exit 1: token_factory bad_request 400: {"detail": "no price"}\n  second line';
  const failed = applyRunEvent(view, { type: "node_status", node_id: "prep", status: "failed", error });
  assert.deepEqual(failed.summary.nodes.map((n) => [n.status, n.error]), [["failed", error], ["pending", null]]);
  assert.equal(applyRunEvent(failed, { type: "node_status", node_id: "prep", status: "running" }).summary.nodes[0].error, null);
  assert.equal(applyRunEvent(view, { type: "log", node_id: "prep", ts: "", level: "INFO", message: "hi" }), view);
});

test("Retry node is enabled only once the run has stopped (failed or cancelled)", () => {
  const statuses = ["pending", "provisioning_gpu", "running", "succeeded", "failed", "cancelled"] as const;
  assert.deepEqual(statuses.filter(canRetry), ["failed", "cancelled"]);
});

test("dropped nodes start from contract defaults: no teacher_kind, vllm-serve keep-alive 30 min", () => {
  assert.equal("teacher_kind" in defaultInputs("synth-distilabel"), false);
  assert.equal(defaultInputs("vllm-serve").keep_alive_min, 30);
  assert.equal(defaultInputs("judge-eval").max_samples, 60);
});

test("nothing made up on screen (team, owner, counts, budget) and no links to the Vast.ai/RunPod pages", () => {
  const read = (path: string) => readFileSync(new URL(`../../apps/web/${path}`, import.meta.url), "utf8");
  const pages = readdirSync(new URL("../../apps/web/app/", import.meta.url), { recursive: true }).map(String);
  for (const page of pages.filter((p) => p.endsWith(".tsx"))) assert.doesNotMatch(read(`app/${page}`), /orbital-research|>EM</, page);
  const sidebar = read("components/Sidebar.tsx");
  for (const fake of [/count: "\d+"/, /orbital|Elena|\$250/, /href: "\/(inference|endpoints)"/]) assert.doesNotMatch(sidebar, fake);
});

test("API datetimes are UTC: a naive one gets Z, one with a zone is kept", () => {
  const t = Date.UTC(2026, 9, 21, 0, 32, 20, 222);
  assert.equal(apiDate("2026-10-21T00:32:20.222824").getTime(), t);
  assert.equal(apiDate("2026-10-21T00:32:20.222Z").getTime(), t);
  assert.equal(apiDate("2026-10-21T02:32:20.222+02:00").getTime(), t);
});

test("tf-finetune's timeout_min stops at 85, under the executor's 90-minute backstop", () => {
  const timeout = NODE_FORMS["tf-finetune"]?.find((f) => f.key === "timeout_min");
  assert.equal(timeout?.max, 85);
  assert.match(timeout?.help ?? "", /85/);
});

const TF = "https://api.tokenfactory.nebius.com/v1";
const tfRef = (model: string, base_model: string | null = null) => ({ base_url: TF, model, api_key_env: "NEBIUS_API_KEY", base_model });

test("compare posts one prompt and two ModelRefs, then streams each side's deltas and its done", async () => {
  // SSE frames split mid-JSON across chunks, plus a comment line, as a proxy may deliver them
  const chunks = ['data: {"i":0,"delta":"Hel', 'lo"}\n\ndata: {"i":1,"delta":"Hi"}\n\n: ping\n\n',
    'data: {"i":0,"done":true,"usd":0.0001}\n\ndata: {"i":1,"done":true,"usd":null}\n\n'];
  let sent: { url: string; init?: RequestInit } | undefined;
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    sent = { url, init };
    return new Response(new ReadableStream({
      start(c) { for (const s of chunks) c.enqueue(new TextEncoder().encode(s)); c.close(); },
    }), { headers: { "Content-Type": "text/event-stream" } });
  };
  const body = { messages: [{ role: "user", content: "hi" }], refs: [tfRef("base"), tfRef("tuned", "base")], max_tokens: 512 };
  const events: unknown[] = [];
  await api.compare(body, (e) => events.push(e));
  assert.equal(`${sent?.init?.method} ${sent?.url}`, "POST http://localhost:8001/compare");
  assert.deepEqual(JSON.parse(String(sent?.init?.body)), body);
  assert.deepEqual(events, [
    { i: 0, delta: "Hello" }, { i: 1, delta: "Hi" }, { i: 0, done: true, usd: 0.0001 }, { i: 1, done: true, usd: null },
  ]);
});

test("a ModelRef pair the server refuses comes back as its readable 422", async () => {
  globalThis.fetch = async () => new Response('{"detail":"refused ModelRef: NEBIUS_API_KEY pairs only with the Token Factory base_url"}', { status: 422 });
  await assert.rejects(api.compare({ messages: [], refs: [tfRef("a"), tfRef("b")], max_tokens: 512 }, () => {}),
    (e) => explainError(e) === "refused ModelRef: NEBIUS_API_KEY pairs only with the Token Factory base_url");
});

test("a JSON artifact is fetched through its download link with no headers, so the 307 to storage needs no preflight", async () => {
  let init: RequestInit | undefined = {};
  globalThis.fetch = async (url: string, i?: RequestInit) => {
    init = i;
    assert.equal(url, "http://localhost:8001/artifacts/a1/download");
    return new Response('{"samples":[]}');
  };
  assert.deepEqual(await api.artifacts.content("/artifacts/a1/download"), { samples: [] });
  assert.equal(init, undefined);
});

const nodeRun = (node_id: string, type: string) => ({ node_id, type, status: "succeeded", usd: 0, error: null, started_at: null, finished_at: null });
const art = (node_id: string, name: string, meta: Record<string, unknown> = {}) =>
  ({ id: `${node_id}-${name}`, node_id, name, kind: "metrics", uri: `r2://b/runs/r1/${node_id}/${name}`,
     download_url: `/artifacts/${node_id}-${name}/download`, meta });
const summary = (nodes: ReturnType<typeof nodeRun>[], artifacts: ReturnType<typeof art>[]) =>
  ({ run_id: "r1", status: "succeeded", cost_usd: 0, error: null, nodes, artifacts }) as never;

test("the eval view reads judge-eval's metrics (eval_summary without samples) and fetches the samples file", () => {
  const stats = { n: 60, judged: 60, wins: 30, ties: 20, losses: 10, errors: 0, win_rate: 0.667, consistency: 0.8 };
  const run = summary([nodeRun("prep", "data-prep"), nodeRun("judge", "judge-eval")],
    [art("judge", "eval_summary"), art("judge", "metrics_json", stats), art("prep", "metrics_json", { total: 3 })]);
  assert.deepEqual(evalOf(run), { stats, samplesUrl: "/artifacts/judge-eval_summary/download" });
  assert.equal(evalOf(summary([nodeRun("prep", "data-prep")], [art("prep", "metrics_json", { total: 3 })])), null);
});

test("the dataset card is the last data-prep node's dataset and metrics, never synth's raw dataset", () => {
  const fields = { action: { distinct: 3, nulls: 0, top: [["like", 2], ["share", 1]] } };
  const run = summary([nodeRun("synth", "synth-distilabel"), nodeRun("prep", "data-prep")],
    [art("synth", "dataset"), art("prep", "dataset"), art("prep", "metrics_json", { total: 3, train: 3, fields })]);
  assert.deepEqual(datasetOf(run), { downloadUrl: "/artifacts/prep-dataset/download", metrics: { total: 3, train: 3, fields } });
  assert.equal(datasetOf(summary([nodeRun("synth", "synth-distilabel")], [art("synth", "dataset")])), null);
});

test("the playground offers the run's ModelRefs: base and tuned first, deduped, endpoint expiry kept, never judge-eval's own llama-server", () => {
  const endpoint = { base_url: "https://ep.example/v1", model: "tuned", api_key_env: "ORCHAPOD_ENDPOINT_TOKEN", base_model: "nvidia/x" };
  const run = summary([nodeRun("deploy", "tf-deploy"), nodeRun("serve", "vllm-serve"), nodeRun("judge", "judge-eval")], [
    art("deploy", "model_ref", { ...tfRef("orchapod-r1", "meta-llama/Llama-3.1-8B-Instruct"), proof: "ok" }),
    art("serve", "model_ref", { ...endpoint, endpoint_id: "e1", expires_at: "2026-10-22T10:00:00Z" }),
    art("judge", "eval_summary"),
    art("judge", "metrics_json", { win_rate: 0.5, base: tfRef("meta-llama/Llama-3.1-8B-Instruct"),
                                   tuned: { ...endpoint, base_model: "nvidia/x" } }),
  ]);
  assert.deepEqual(modelRefsOf(run), [
    { label: "base", ...tfRef("meta-llama/Llama-3.1-8B-Instruct"), expires_at: undefined },
    { label: "tuned", ...endpoint, expires_at: "2026-10-22T10:00:00Z" },
    { label: "deploy.model_ref", ...tfRef("orchapod-r1", "meta-llama/Llama-3.1-8B-Instruct"), expires_at: undefined },
  ]);
  const local = { base_url: "http://127.0.0.1:8081/v1", model: "q4", api_key_env: "", base_model: null };
  assert.deepEqual(modelRefsOf(summary([nodeRun("judge", "judge-eval")], [art("judge", "eval_summary"),
    art("judge", "metrics_json", { win_rate: 1, base: local, tuned: { ...local, model: "f16" } })])), []);
});

test("no token reaches the browser: nothing reads meta.api_key, sends an Authorization header or calls /inference/extend", () => {
  const found = ["app", "components", "lib"].flatMap((dir) =>
    readdirSync(new URL(`../../apps/web/${dir}/`, import.meta.url), { recursive: true }).map(String)
      .filter((f) => /\.tsx?$/.test(f))
      .flatMap((f) => readFileSync(new URL(`../../apps/web/${dir}/${f}`, import.meta.url), "utf8")
        .match(/\.api_key\b|["']Authorization["']|inference\/extend/g)?.map((m) => `${dir}/${f}: ${m}`) ?? []));
  assert.deepEqual(found, []);
});
