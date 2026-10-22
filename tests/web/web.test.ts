// Web unit tests. Run from the repo root: node --test "tests/web/*.test.ts"
// (Node >= 22.18 strips the types itself, so there is nothing to install.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { yamlValue, buildYamlFromGraph, planYaml } from "../../apps/web/lib/workflowYaml.ts";
import { api, apiDate, cancelToken, capNote, demoNote, explainError, TOAST_EVENT, toastError } from "../../apps/web/lib/api.ts";
import { applyCompareEvent, applyRunEvent, canRetry, finished, runShown } from "../../apps/web/lib/runEvents.ts";
import { defaultInputs, NODE_FORMS } from "../../apps/web/lib/nodeForms.ts";
import { datasetOf, evalOf, lossPoints, lossSources, modelRefsOf } from "../../apps/web/lib/results.ts";

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
  // Outside the agent a 502/503 is not about Nemotron planning: the server's detail says what failed
  assert.equal(explainError(http(502, "/compare", { detail: "refs[1] (tuned) failed; the API log has the cause" })),
    "502 on /compare: refs[1] (tuned) failed; the API log has the cause");
  assert.equal(explainError(http(503, "/compare", { detail: "the kill switch is on (ORCHAPOD_KILL_SWITCH)" })),
    "503 on /compare: the kill switch is on (ORCHAPOD_KILL_SWITCH)");
  // a cancel without the run's token (the run page's toast): one sentence, not the header name the API's detail gives
  assert.equal(explainError(http(403, "/runs/r1/cancel", { detail: "cancelling this run needs its cancel token (X-Orchapod-Cancel-Token, "
    + "returned when it started) or the admin" })), "Only the tab that started this run can cancel it (403).");
});

/** Installs Web Storage stand-ins for one call: Node 22 (CI) has none, and Node 26's would outlive the test. */
async function withStorage(stores: Record<string, object>, fn: () => Promise<void>) {
  const saved = Object.keys(stores).map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)] as const);
  for (const [name, value] of Object.entries(stores)) Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  try { await fn(); } finally {
    for (const [name, d] of saved) if (d) Object.defineProperty(globalThis, name, d); else delete (globalThis as Record<string, unknown>)[name];
  }
}
const storage = () => {
  const items = new Map<string, string>();
  return { items, getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => void items.set(k, v) };
};

test("a run's cancel token stays in this tab's sessionStorage by run id and leaves only as Cancel's X-Orchapod-Cancel-Token", async () => {
  const session = storage(), local = storage();
  const sent: { url: string; headers: Record<string, string> }[] = [];
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    sent.push({ url, headers: { ...(init?.headers as Record<string, string>) } });
    return new Response(JSON.stringify(url.endsWith("/start") ? { id: "r1", status: "provisioning_gpu", cancel_token: "tok-1" }
      : url.endsWith("/agent/run") ? { run_id: "r2", workflow_id: "w2", estimate: {}, cancel_token: "tok-2" }
      : { id: "r2", status: "cancelled" }));
  };
  await withStorage({ sessionStorage: session, localStorage: local }, async () => {
    // start and /agent/run return it once: kept here, never handed to the page
    assert.equal("cancel_token" in await api.runs.start("r1"), false);
    assert.equal("cancel_token" in await api.agent.run("intent", { name: "p", nodes: [] }), false);
    assert.deepEqual([...session.items], [["orchapod:cancel-token:r1", "tok-1"], ["orchapod:cancel-token:r2", "tok-2"]]);
    assert.equal(local.items.size, 0);
    assert.deepEqual([cancelToken("r1"), cancelToken("r2"), cancelToken("r3")], ["tok-1", "tok-2", null]);
    await api.runs.cancel("r2");
    await api.runs.cancel("r3"); // started elsewhere: no header (the run page keeps its Cancel disabled)
    assert.deepEqual(sent.slice(2).map((s) => [s.url, s.headers["X-Orchapod-Cancel-Token"]]),
      [["http://localhost:8001/runs/r2/cancel", "tok-2"], ["http://localhost:8001/runs/r3/cancel", undefined]]);
    assert.ok(sent.every((s) => !s.url.includes("tok-"))); // never in a URL
  });
  // storage switched off (Safari's SecurityError): the run still starts, and only the admin can cancel it
  const off = { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("SecurityError"); } };
  await withStorage({ sessionStorage: off }, async () => {
    assert.equal((await api.runs.start("r1")).id, "r1");
    assert.equal(cancelToken("r1"), null);
  });
});

test("canvas Save on a workflow with runs gets the API's 409 (read-only to visitors); Save a copy posts the edited YAML as \"<name> (copy)\"", async () => {
  const calls: unknown[][] = [];
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    calls.push([init?.method, url, JSON.parse(String(init?.body))]);
    return init?.method === "PUT"
      ? new Response('{"detail":"this workflow has runs, so it is read-only on the public app; save a copy as a new workflow"}', { status: 409 })
      : new Response('{"id":"w2","name":"golden (copy)"}', { status: 201 });
  };
  const yaml = "name: golden\nnodes:\n  - id: prep\n    type: data-prep";
  await assert.rejects(api.workflows.update("w1", { yaml }), (e: { status: number }) => e.status === 409);
  assert.equal((await api.workflows.copy("golden", yaml)).id, "w2");
  assert.deepEqual(calls, [["PUT", "http://localhost:8001/workflows/w1", { yaml }],
                           ["POST", "http://localhost:8001/workflows", { name: "golden (copy)", yaml }]]);
});

test("the run page reads GET /runs/{id}/summary and retries with POST /runs/{id}/nodes/{node_id}/retry", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return new Response("{}");
  };
  await api.runs.summary("r1");
  await api.runs.retry("r1", "prep");
  await api.runs.list(undefined, 500); // /runs asks for 500: the seeded golden run keeps its old timestamps
  await api.runs.list("w1");
  await api.runs.list();
  assert.deepEqual(calls, ["GET http://localhost:8001/runs/r1/summary", "POST http://localhost:8001/runs/r1/nodes/prep/retry",
    "GET http://localhost:8001/runs?limit=500", "GET http://localhost:8001/runs?workflow_id=w1", "GET http://localhost:8001/runs"]);
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
  assert.deepEqual(statuses.filter(finished), ["succeeded", "failed", "cancelled"]); // the loss chart's and artifact list's "this run is over"
});

test("dropped nodes start from contract defaults: no teacher_kind, vllm-serve keep-alive 30 min, unsloth-train on R25's student", () => {
  assert.equal("teacher_kind" in defaultInputs("synth-distilabel"), false);
  assert.equal(defaultInputs("vllm-serve").keep_alive_min, 30);
  assert.equal(defaultInputs("unsloth-train").model, "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"); // as the palette says
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

test("quantize takes lora_adapter and judge-eval tuned_lora, both optional and in the contract's words; tf-deploy's help says it is retired", () => {
  const help = (type: "quantize" | "judge-eval", key: string) => NODE_FORMS[type]?.find((f) => f.key === key)?.help;
  assert.equal(help("quantize", "lora_adapter"), "An r2 PEFT LoRA dir trained on model, such as unsloth-train's or tf-finetune's lora_adapter.");
  assert.equal(help("judge-eval", "tuned_lora"), "quantize's gguf_lora, which the tuned side's llama-server applies with --lora over tuned_model_ref's GGUF, "
    + "so tuned = the base GGUF plus the adapter; a tuned ref that is not a GGUF, or a LoRA file that is not GGUF, → exit 1; "
    + "the summary's tuned ModelRef then has model = the LoRA's URI and base_model = the GGUF's.");
  // no default: a dropped node sends neither until it is filled in, and quantize keeps the inputs it had
  assert.deepEqual(defaultInputs("quantize"), { model: "", method: "gguf", precision: "q4_k_m" });
  assert.equal("tuned_lora" in defaultInputs("judge-eval"), false);
  // a form replaces the generic input list, so it must cover every input of the node's model (packages/workflow_schema/models.py)
  assert.deepEqual(NODE_FORMS.quantize?.map((f) => f.key), ["model", "method", "precision", "bits", "keep_f16", "lora_adapter"]);
  assert.equal(NODE_FORMS["tf-deploy"]?.length, 2);
  for (const f of NODE_FORMS["tf-deploy"] ?? []) assert.match(f.help, /^Retired, kept for old workflows only/, f.key);
  assert.doesNotMatch(NODE_FORMS["judge-eval"]?.find((f) => f.key === "tuned_model_ref")?.help ?? "", /tf-deploy/);
});

test("the palette lists the golden path first (R25) and no node the registry hides: tf-deploy is retired (R24)", () => {
  const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
  const palette = [...read("apps/web/components/canvas/NodePalette.tsx").matchAll(/\{ type: "([a-z0-9-]+)",/g)].map((m) => m[1]);
  assert.deepEqual(palette, ["web-research", "synth-distilabel", "data-prep", "unsloth-train", "vllm-serve", "judge-eval",
    "tf-finetune", "quantize", "hf-download", "distill-sft", "lm-eval"]);
  // The registry's `"hidden": True` rows, read as text (the web job of CI has no Python); a row is NodeType.X: {…} or NODE_REGISTRY[NodeType.X] = {…}.
  const hidden = read("packages/workflow_schema/models.py").split(/(?=NodeType\.[A-Z0-9_]+(?:: |\] = )\{)/)
    .filter((row) => row.includes('"hidden": True')).map((row) => row.match(/^NodeType\.([A-Z0-9_]+)/)![1].toLowerCase().replaceAll("_", "-"));
  assert.ok(["tf-deploy", "s3-import", "hf-import"].every((t) => hidden.includes(t)), `read the registry's hidden rows: ${hidden}`);
  // distill-sft and lm-eval are hidden from the planner (off the demo path) but have containers, and the brief keeps them on the palette
  assert.deepEqual(palette.filter((t) => hidden.includes(t) && !["distill-sft", "lm-eval"].includes(t)), []);
});

test("the template gallery reads GET /agent/templates", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return new Response("[]");
  };
  assert.deepEqual(await api.agent.templates(), []);
  assert.deepEqual(calls, ["GET http://localhost:8001/agent/templates"]);
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

test("no token reaches the browser: nothing reads meta.api_key, sends an Authorization header, asks for an HF token or calls /inference/extend", () => {
  const found = ["app", "components", "lib"].flatMap((dir) =>
    readdirSync(new URL(`../../apps/web/${dir}/`, import.meta.url), { recursive: true }).map(String)
      .filter((f) => /\.tsx?$/.test(f))
      .flatMap((f) => readFileSync(new URL(`../../apps/web/${dir}/${f}`, import.meta.url), "utf8")
        .match(/\.api_key\b|["']Authorization["']|\bhf_token\b|hfToken|inference\/extend/g)?.map((m) => `${dir}/${f}: ${m}`) ?? []));
  assert.deepEqual(found, []);
});

test("a compare side appends deltas, closes on done and keeps a failed stream's error; other events change nothing", () => {
  const open = [{ text: "", done: false, usd: null }, { text: "", done: false, usd: null }];
  let sides = applyCompareEvent(open, { i: 0, delta: "Hel" });
  sides = applyCompareEvent(sides, { i: 0, delta: "lo" });
  sides = applyCompareEvent(sides, { i: 1 } as never); // no delta: nothing to append (never "undefined")
  sides = applyCompareEvent(sides, { i: 0, done: true, usd: 0.0001 });
  sides = applyCompareEvent(sides, { i: 1, done: true, usd: null, error: "the model call failed mid-stream" });
  assert.deepEqual(sides, [
    { text: "Hello", done: true, usd: 0.0001, error: undefined },
    { text: "", done: true, usd: null, error: "the model call failed mid-stream" },
  ]);
});

const template = (usd: number, fits?: boolean) => {
  const plan = { name: "real-estate-compliance-llama-3b", nodes: [] };
  return { slug: "re", title: "Llama 3B", intent: "i", rationale: "", plan, estimate: { usd: usd * 2, minutes: 40, by_node: {} },
           reduced: { plan, estimate: { usd, minutes: 20, by_node: {} } }, ...(fits === undefined ? {} : { fits }) };
};

test("a template above the caller's run cap (fits: false) says why, from its reduced estimate, and links to the golden run", () => {
  assert.deepEqual(capNote(template(0.88, false)),
    { text: "about $0.88 — above the public demo's per-run cap", href: "/runs?q=real-estate-compliance-llama-3b" });
  assert.equal(capNote(template(0.15, true)), null);
  assert.equal(capNote(template(0.15)), null); // no `fits` (an API before backend-w3's fix round): runnable
});

test("the demo banner says what a run costs (the estimates one-click Run uses) and that public runs are capped", () => {
  assert.equal(demoNote(null), "Every run shows its estimated cost before you press Run. Public runs are capped per run and per day.");
  assert.equal(demoNote([template(0.15, true), template(0.88, false), template(0.02)]),
    "Every run shows its estimated cost before you press Run: $0.02 to $0.88 for the templates below. "
    + "Public runs are capped per run and per day; a template above the per-run cap links to its golden run instead.");
});

test("a failed fetch with no error display of its own raises one readable toast", () => {
  const raised: CustomEvent[] = [];
  Object.assign(globalThis, { dispatchEvent: (e: CustomEvent) => raised.push(e) });
  try {
    toastError("Couldn't load runs")(new TypeError("Failed to fetch"));
    // a non-JSON error body (S3 AccessDenied XML names the bucket, key and request id) is cut to 300 characters
    toastError("Couldn't load the loss curve")(Object.assign(new Error("403"), { status: 403, path: "/x", body: "<Error>" + "k".repeat(500) }));
  } finally {
    delete (globalThis as { dispatchEvent?: unknown }).dispatchEvent;
  }
  assert.deepEqual(raised.slice(0, 1).map((e) => [e.type, e.detail]),
    [[TOAST_EVENT, "Couldn't load runs: Can't reach the Orchapod API at http://localhost:8001. Is it running?"]]);
  assert.equal(raised[1].detail.length, 300);
  assert.match(raised[1].detail, /^Couldn't load the loss curve: 403 on \/x: <Error>k+$/);
});

test("the loss chart fills on load from each fine-tune node's loss_curve: its metrics meta, else the file behind download_url", () => {
  const tf = [{ step: 1, train_loss: 1.0, valid_loss: 1.0 }, { step: 2, train_loss: 0.5, valid_loss: 0.5 }]; // tf-finetune/run.py:140
  const run = summary([nodeRun("prep", "data-prep"), nodeRun("tune", "tf-finetune"), nodeRun("train", "unsloth-train"),
                       nodeRun("big", "tf-finetune")], [
    art("prep", "metrics_json", { total: 3 }),
    art("tune", "job", { job_id: "ftjob-1" }), art("tune", "metrics_json", { stub: true, loss_curve: tf }),
    art("train", "train_metrics_json"), // unsloth-train/run.py:177 writes the curve into the file only
    art("big", "metrics_json", { truncated: true }), // write_metrics keeps metadata only up to 16 KB
  ]);
  assert.deepEqual(lossSources(run), [
    { node_id: "tune", rows: tf },
    { node_id: "train", url: "/artifacts/train-train_metrics_json/download" },
    { node_id: "big", url: "/artifacts/big-metrics_json/download" },
  ]);
  assert.deepEqual(lossPoints([{ node_id: "tune", rows: tf }], []), [
    { node_id: "tune", step: 1, loss: 1.0, valid_loss: 1.0 }, { node_id: "tune", step: 2, loss: 0.5, valid_loss: 0.5 },
  ]);
  // a checkpoint with only a validation loss is drawn on that line alone; a row with neither loss is not a point
  const sparse = [...tf, { step: 3, train_loss: null, valid_loss: 0.4 }, { step: 4, train_loss: null, valid_loss: null }];
  assert.deepEqual(lossPoints([{ node_id: "tune", rows: sparse }], []).slice(2), [{ node_id: "tune", step: 3, valid_loss: 0.4 }]);
  assert.deepEqual(lossSources(summary([nodeRun("prep", "data-prep")], [art("prep", "metrics_json", { total: 3 })])), []);
});

test("live progress events append to the loss curve, and a step the curve already has is drawn once", () => {
  const unsloth = [{ step: 10, loss: 2.4 }, { step: 20, loss: 1.9 }]; // unsloth-train/run.py:177
  const progress = (node_id: string, step: number, loss: number | null) => ({ type: "progress" as const, node_id, step, total: 500, loss });
  const events = [progress("train", 20, 1.9), progress("train", 30, 1.5), progress("prep", 3, null),
                  { type: "log" as const, node_id: "train", ts: "", level: "INFO", message: "loss=9" }];
  assert.deepEqual(lossPoints([{ node_id: "train", rows: unsloth }], events as never), [
    { node_id: "train", step: 10, loss: 2.4 }, { node_id: "train", step: 20, loss: 1.9 }, { node_id: "train", step: 30, loss: 1.5 },
  ]);
  // a run still training has no metrics yet: the events alone draw the chart, as before
  assert.deepEqual(lossPoints([], [progress("train", 10, 2.4)] as never), [{ node_id: "train", step: 10, loss: 2.4 }]);
  // the curve is the node's own record: an event at the same step neither replaces it nor drops its valid_loss
  assert.deepEqual(lossPoints([{ node_id: "tune", rows: [{ step: 2, train_loss: 0.5, valid_loss: 0.6 }] }], [progress("tune", 2, 0.7)] as never),
    [{ node_id: "tune", step: 2, loss: 0.5, valid_loss: 0.6 }]);
});

test("the golden-run link matches its workflow name exactly and hides runs never started; a typed search is a substring", () => {
  const golden = { id: "r1", workflow_name: "golden", status: "succeeded" };
  const copy = { id: "r2", workflow_name: "golden (copy)", status: "succeeded" };
  const pending = { id: "r3", workflow_name: "golden", status: "pending" };
  assert.deepEqual([golden, copy, pending].filter(r => runShown(r, "golden", "golden")), [golden]);
  assert.deepEqual([golden, copy, pending].filter(r => runShown(r, "golden", "")), [golden, copy, pending]);  // typed, not linked
  assert.deepEqual([golden, copy].filter(r => runShown(r, "copy", "golden")), [copy]);  // the box was edited
});
