// Web unit tests. Run from the repo root: node --test "tests/web/*.test.ts"
// (Node >= 22.18 strips the types itself, so there is nothing to install.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { yamlValue, buildYamlFromGraph, planYaml, STARTER_YAML } from "../../apps/web/lib/workflowYaml.ts";
import { api, apiDate, cancelToken, capNote, demoNote, explainError, mergeLogs, TOAST_EVENT, toastError } from "../../apps/web/lib/api.ts";
import { applyCompareEvent, applyRunEvent, canRetry, finished, nodeStyle, providerName, REPORT_WAIT_MS, reportNext, runIdOf, runShown, seenFinishedAt, splitReport, whereRuns } from "../../apps/web/lib/runEvents.ts";
import { defaultInputs, NODE_FORMS } from "../../apps/web/lib/nodeForms.ts";
import { datasetOf, evalOf, lossPoints, lossSources, modelRefsOf, refName, resultTab } from "../../apps/web/lib/results.ts";

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

test("the Logs tab reads GET /runs/{id}/logs?limit=2000, of the selected node when there is one", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (url: string) => { calls.push(url); return new Response('[{"ts":"2026-10-25T10:00:00","level":"INFO","node_id":"train","message":"hi"}]'); };
  assert.equal((await api.runs.logs("r1"))[0].message, "hi");
  await api.runs.logs("r1", "train step");
  assert.deepEqual(calls, ["http://localhost:8001/runs/r1/logs?limit=2000", "http://localhost:8001/runs/r1/logs?limit=2000&node_id=train%20step"]);
});

test("stored log lines and live ones merge without duplicates, in arrival order (backend-w9's contract, mocked)", () => {
  const line = (ts: string, message: string, node_id = "train") => ({ ts, level: "INFO", node_id, message });
  // the API's naive UTC against the SDK's own stamp (microseconds, +00:00): one line, whatever the notation
  const stored = [line("2026-10-25T10:00:00.100000", "loading"), line("2026-10-25T10:00:01.500000", "step 1")];
  const live = [line("2026-10-25T10:00:01.500000+00:00", "step 1"), line("2026-10-25T10:00:02Z", "step 2")];
  assert.deepEqual(mergeLogs(stored, live).map((l) => l.message), ["loading", "step 1", "step 2"]);
  assert.deepEqual(mergeLogs([], live).map((l) => l.message), ["step 1", "step 2"]); // nothing stored yet (or the fetch failed)
  assert.deepEqual(mergeLogs(stored, []), stored);
  // two real lines that look alike both show: a stored copy hides one live copy, not every one
  const twin = line("2026-10-25T10:00:03Z", "retrying");
  assert.equal(mergeLogs([twin], [twin, twin]).length, 2);
  assert.equal(mergeLogs([], [twin, twin]).length, 2);
  // the same text from another node, or at another time, is another line
  assert.equal(mergeLogs([line("2026-10-25T10:00:03Z", "x", "a")], [line("2026-10-25T10:00:03Z", "x", "b")]).length, 2);
  assert.equal(mergeLogs([line("2026-10-25T10:00:03Z", "x")], [line("2026-10-25T10:00:04Z", "x")]).length, 2);
  // a socket open longer than the stored window has older lines too: they go before the stored ones, not after
  assert.deepEqual(mergeLogs([line("2026-10-25T10:05:00Z", "new")], [line("2026-10-25T10:01:00Z", "old")]).map((l) => l.message), ["old", "new"]);
  assert.equal(stored.length, 2); // the inputs are not touched
  // nodes keep their own clocks, so the rest is not sorted: a line that arrived later stays later even when its stamp is earlier
  const [a5, b3] = [line("2026-10-25T10:00:05Z", "a", "a"), line("2026-10-25T10:00:03Z", "b", "b")];
  assert.deepEqual(mergeLogs([], [a5, b3]).map((l) => l.message), ["a", "b"]);
  const first = line("2026-10-25T10:00:01Z", "first", "a");
  assert.deepEqual(mergeLogs([first], [a5, b3]).map((l) => l.message), ["first", "a", "b"]);
  // only the live lines older than the first stored one move to the front, in the order they arrived
  const [o1, o2] = [line("2026-10-25T09:59:50Z", "o1", "a"), line("2026-10-25T09:59:40Z", "o2", "a")];
  assert.deepEqual(mergeLogs([first], [o1, a5, o2]).map((l) => l.message), ["o1", "o2", "first", "a"]);
});

test("a node card says where its step runs: a Nebius resource adds its kind, short id and live state (backend-w9's contract, mocked)", () => {
  assert.equal(providerName("nebius"), "Nebius");
  assert.equal(providerName("local-docker"), "Local Docker");
  assert.equal(providerName("vastai"), "vastai"); // any other as it is
  const id = "aijob-e00h5k8m3p7r2";
  assert.equal(whereRuns({ provider: "nebius", resource: { kind: "job", id, state: "IMAGE_PULLING" } }), "Nebius Job …k8m3p7r2 · IMAGE_PULLING");
  assert.equal(whereRuns({ provider: "nebius", resource: { kind: "endpoint", id: "ep-1", state: "RUNNING" } }), "Nebius Endpoint ep-1 · RUNNING"); // a short id whole
  assert.equal(whereRuns({ provider: "nebius", resource: { kind: "job", id, state: null } }), "Nebius Job …k8m3p7r2"); // the state is live only while the node runs
  // the real shape of vllm-serve: its container runs on local-docker, and the endpoint it created is the Nebius resource (tests/api/test_executor.py)
  const ep = "aiendpoint-e00zz9y8x7w6";
  assert.equal(whereRuns({ provider: "local-docker", resource: { kind: "endpoint", id: ep, state: "RUNNING" } }), "Nebius Endpoint …z9y8x7w6 · RUNNING");
  assert.equal(whereRuns({ provider: "local-docker", resource: { kind: "endpoint", id: ep, state: null } }), "Nebius Endpoint …z9y8x7w6"); // done, not asked
  assert.equal(whereRuns({ provider: null, resource: { kind: "job", id, state: "RUNNING" } }), "Nebius Job …k8m3p7r2 · RUNNING"); // the resource says it
  assert.equal(whereRuns({ provider: "nebius", resource: null }), "Nebius"); // its Job is not created yet
  assert.equal(whereRuns({ provider: "local-docker", resource: null }), "Local Docker");
  assert.equal(whereRuns({ provider: null, resource: null }), ""); // not started
  assert.equal(whereRuns({}), ""); // an API that predates the fields
});

test("the canvas takes ?run= only when it is a run id, so nothing else reaches an API path", () => {
  const id = "d20d30f3-768f-4989-b974-cac3d9b47495";
  assert.equal(runIdOf(id), id);
  assert.equal(runIdOf(id.toUpperCase()), id.toUpperCase());
  for (const bad of [null, "", "abc", `${id}0`, id.slice(1), "../../admin/x".padEnd(36, "a"), `${id.slice(0, 35)}/`, `${id.slice(0, 35)}?`, id.replace("-", " ")]) {
    assert.equal(runIdOf(bad), null, String(bad));
  }
});

test("a canvas node is drawn by its run status: pending grey, running blue and pulsing, succeeded green, failed red; no run, no style", () => {
  assert.equal(nodeStyle(undefined), null); // the canvas without ?run= is unchanged
  const styles = (["pending", "running", "succeeded", "failed"] as const).map((s) => nodeStyle(s)!);
  assert.deepEqual(styles.map((s) => s.dot), ["#C1C7D0", "#0052CC", "#00875A", "#DE350B"]);
  assert.deepEqual(styles.map((s) => s.pulse), [false, true, false, false]); // only the step that is executing pulses
  assert.equal(new Set(styles.map((s) => s.ring)).size, 4); // four rings that differ
  for (const [i, s] of styles.entries()) assert.ok(s.ring.includes(styles[i].dot), s.ring); // each ring is its dot's colour
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
  for (const page of pages.filter((p) => p.endsWith(".tsx"))) assert.doesNotMatch(read(`app/${page}`), /orbital-research|>EM<|LLM Fine-tuning Platform/, page);
  const sidebar = read("components/Sidebar.tsx");
  for (const fake of [/count: "\d+"/, /orbital|Elena|\$250/, /href: "\/(inference|endpoints)"/]) assert.doesNotMatch(sidebar, fake);
});

test("no sidebar link leads to a page that says \"Coming soon\", or to no page at all", () => {
  const web = (path: string) => new URL(`../../apps/web/${path}`, import.meta.url);
  const hrefs = [...readFileSync(web("components/Sidebar.tsx"), "utf8").matchAll(/href: "(\/[a-z-]*)"/g)].map((m) => m[1]);
  assert.ok(hrefs.includes("/agent") && hrefs.includes("/runs"), `read the sidebar's links: ${hrefs}`);
  for (const href of hrefs) {
    const page = web(`app${href === "/" ? "" : href}/page.tsx`);
    assert.ok(existsSync(page), `${href}: no page`);
    assert.doesNotMatch(readFileSync(page, "utf8"), /coming soon/i, href);
  }
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

test("the golden path's forms: quantize lora_adapter, judge-eval tuned_lora, unsloth-train merge and vllm-serve lora_adapter and keep_alive_min, in the contract's words; tf-deploy's help says it is retired", () => {
  const help = (type: "quantize" | "judge-eval" | "unsloth-train" | "vllm-serve", key: string) => NODE_FORMS[type]?.find((f) => f.key === key)?.help;
  assert.equal(help("quantize", "lora_adapter"), "An r2 PEFT LoRA dir trained on model, such as unsloth-train's or tf-finetune's lora_adapter.");
  assert.equal(help("judge-eval", "tuned_lora"), "quantize's gguf_lora, which the tuned side's llama-server applies with --lora over tuned_model_ref's GGUF, "
    + "so tuned = the base GGUF plus the adapter; a tuned ref that is not a GGUF, or a LoRA file that is not GGUF, → exit 1; "
    + "the summary's tuned ModelRef then has model = the LoRA's URI and base_model = the GGUF's.");
  // no default: a dropped node sends neither until it is filled in, and quantize keeps the inputs it had
  assert.deepEqual(defaultInputs("quantize"), { model: "", method: "gguf", precision: "q4_k_m" });
  assert.equal("tuned_lora" in defaultInputs("judge-eval"), false);
  // a form replaces the generic input list, so it must cover every input of the node's model (packages/workflow_schema/models.py)
  assert.deepEqual(NODE_FORMS.quantize?.map((f) => f.key), ["model", "method", "precision", "bits", "keep_f16", "lora_adapter"]);
  assert.deepEqual(NODE_FORMS["unsloth-train"]?.map((f) => f.key), ["model", "train_data", "eval_data", "lora_r", "lora_alpha", "max_steps",
    "learning_rate", "target_modules", "checkpoint_steps", "load_in_4bit", "merge"]);
  assert.deepEqual(NODE_FORMS["vllm-serve"]?.map((f) => f.key), ["model", "lora_adapter", "max_model_len", "keep_alive_min", "served_model_name",
    "gpu_memory_utilization", "dtype", "platform", "preset"]);
  // unsloth-train (docs/contracts.md "unsloth-train")
  assert.equal(help("unsloth-train", "merge"), "false skips the 16-bit merge and the ~16 GB merged_model upload, for plans that read only lora_adapter, such as vllm-serve --enable-lora or quantize.");
  assert.equal(help("unsloth-train", "load_in_4bit"), "QLoRA; false, i.e. 16-bit LoRA.");
  assert.equal(help("unsloth-train", "eval_data"), "data-prep's eval_jsonl. \"\" or an empty file = none.");
  // vllm-serve (docs/contracts.md "vllm-serve", R14 for Lane B's 15)
  assert.equal(help("vllm-serve", "model"), "HF id, or an r2 dir such as merged_model.");
  assert.equal(help("vllm-serve", "lora_adapter"), "r2 PEFT dir. Served as tuned (--enable-lora) beside the base on the same endpoint, so base and tuned share one serving stack.");
  assert.equal(help("vllm-serve", "keep_alive_min"), "L40S costs $1.55/h against the $3 run cap; max 120. The backend deletes the endpoint after this; GPU time bills until then. "
    + "Lane B plans use 15; the default 30 stays for other plans.");
  assert.equal(help("vllm-serve", "served_model_name"), "The model's name in /v1/models. Default: the HF id; \"tuned\" for an r2 dir or adapter.");
  assert.equal(NODE_FORMS["vllm-serve"]?.find((f) => f.key === "keep_alive_min")?.max, 120);
  // the registry's defaults (packages/workflow_schema/models.py): a required input starts empty, an optional one with none is absent
  assert.deepEqual(defaultInputs("unsloth-train"), { model: "nvidia/Llama-3.1-Nemotron-Nano-8B-v1", train_data: "", eval_data: "", lora_r: 16, lora_alpha: 32,
    max_steps: 500, learning_rate: 0.0002, target_modules: "all-linear", checkpoint_steps: 100, load_in_4bit: false, merge: true });
  assert.deepEqual(defaultInputs("vllm-serve"), { model: "", max_model_len: 8192, keep_alive_min: 30, gpu_memory_utilization: 0.9, dtype: "bfloat16",
    platform: "gpu-l40s-a", preset: "1gpu-8vcpu-32gb" });
  assert.equal(NODE_FORMS["tf-deploy"]?.length, 2);
  for (const f of NODE_FORMS["tf-deploy"] ?? []) assert.match(f.help, /^Retired, kept for old workflows only/, f.key);
  assert.doesNotMatch(NODE_FORMS["judge-eval"]?.find((f) => f.key === "tuned_model_ref")?.help ?? "", /tf-deploy/);
});

test("the palette is the golden path first (R25), then exactly the node types the registry shows: hidden = off the demo path, tf-deploy retired (R24)", () => {
  const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
  const palette = [...read("apps/web/components/canvas/NodePalette.tsx").matchAll(/\{ type: "([a-z0-9-]+)",/g)].map((m) => m[1]);
  // The registry's rows, read as text (the web job of CI has no Python); a row is NodeType.X: {…} or NODE_REGISTRY[NodeType.X] = {…}.
  const rows = read("packages/workflow_schema/models.py").split(/(?=NodeType\.[A-Z0-9_]+(?:: |\] = )\{)/).filter((r) => r.startsWith("NodeType."));
  const visible = rows.filter((r) => !r.includes('"hidden": True')).map((r) => r.match(/^NodeType\.([A-Z0-9_]+)/)![1].toLowerCase().replaceAll("_", "-"));
  const known = [...read("apps/web/components/canvas/OrchaNode.tsx").matchAll(/^ {2}"([a-z0-9-]+)": +\{ label:/gm)].map((m) => m[1]); // NODE_META: what the web app can draw
  assert.deepEqual(palette.slice(0, 6), ["web-research", "synth-distilabel", "data-prep", "unsloth-train", "vllm-serve", "judge-eval"]);
  assert.deepEqual([...palette].sort(), visible.filter((t) => known.includes(t)).sort());
});

test("the New Workflow starter is intent #2's shape, synth-distilabel into data-prep, and uses only palette node types", () => {
  const palette = [...readFileSync(new URL("../../apps/web/components/canvas/NodePalette.tsx", import.meta.url), "utf8").matchAll(/\{ type: "([a-z0-9-]+)",/g)].map((m) => m[1]);
  const types = [...STARTER_YAML.matchAll(/^ {2}- id: \w+\n {4}type: ([a-z0-9-]+)$/gm)].map((m) => m[1]);
  assert.deepEqual(types, ["synth-distilabel", "data-prep"]);
  assert.deepEqual(types.filter((t) => !palette.includes(t)), []);
  assert.match(STARTER_YAML, /^ {4}needs: \[synth\]$/m); // data-prep reads what synth wrote
  assert.match(STARTER_YAML, /^ {6}dataset: \$\{\{ nodes\.synth\.outputs\.dataset \}\}$/m);
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

test("a succeeded run opens on its eval, else its dataset, and a snapshot never takes back a tab the user picked", () => {
  const prep = [nodeRun("prep", "data-prep")];
  const judged = summary([...prep, nodeRun("judge", "judge-eval")],
    [art("prep", "dataset"), art("judge", "eval_summary"), art("judge", "metrics_json", { win_rate: 0.5 })]);
  assert.equal(resultTab(judged, false), "eval");
  assert.equal(resultTab(summary(prep, [art("prep", "dataset")]), false), "dataset");
  assert.equal(resultTab(summary(prep, []), false), null); // nothing to show yet
  assert.equal(resultTab({ ...judged, status: "running" }, false), null); // the eval tab exists a moment before the run ends: not opened
  assert.equal(resultTab(judged, true), null); // the user is on the compare tab when the last snapshot lands: it stays
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

test("a side is named by its label and by its model only when that differs: the served adapter \"tuned\" is not \"tuned · tuned\"", () => {
  const ep = (model: string) => ({ base_url: "http://stub.invalid/v1", model, api_key_env: "ORCHAPOD_ENDPOINT_TOKEN", base_model: "meta-llama/Llama-3.2-3B-Instruct" });
  // the seeded golden run's refs: the base by its Hugging Face id, the adapter served as "tuned"
  const run = summary([nodeRun("judge", "judge-eval")], [art("judge", "eval_summary"),
    art("judge", "metrics_json", { win_rate: 0.5, base: ep("meta-llama/Llama-3.2-3B-Instruct"), tuned: ep("tuned") })]);
  assert.deepEqual(modelRefsOf(run).map((r) => refName(r.label, r.model)), ["base · meta-llama/Llama-3.2-3B-Instruct", "tuned"]);
  assert.equal(refName("tuned", "orchapod-r1"), "tuned · orchapod-r1"); // a name that says more is kept
  assert.equal(refName("deploy.model_ref", "tuned"), "deploy.model_ref · tuned");
  assert.equal(refName("tuned", undefined), "tuned"); // the eval line's stats may lack a model
  assert.equal(refName("base", "meta-llama/Llama-3.2-3B-Instruct", " "), "base meta-llama/Llama-3.2-3B-Instruct"); // the eval line's separator
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

test("the report card polls until the report is ready, also after the run ended, and gives up 60 s after it ended", () => {
  const t0 = 1_000_000; // when a poll first saw the run finished
  assert.equal(REPORT_WAIT_MS, 60_000);
  assert.equal(reportNext(false, undefined, t0 + 6 * 3_600_000), "wait"); // the run is still going: no bound, however long it takes
  assert.equal(reportNext(false, t0, t0), "wait"); // just ended: the API writes the report in the background
  assert.equal(reportNext(false, t0, t0 + REPORT_WAIT_MS - 1), "wait");
  assert.equal(reportNext(false, t0, t0 + REPORT_WAIT_MS), "gone"); // "Report unavailable, see the run page"
  assert.equal(reportNext(true, undefined, t0), "done");
  assert.equal(reportNext(true, t0, t0 + 2 * REPORT_WAIT_MS), "done"); // a report that lands late is still shown
});

test("a Retry node starts the report's 60 s wait over: finished, running again, finished again", () => {
  const t0 = 1_000_000;
  let endedAt = seenFinishedAt("failed", undefined, t0); // a poll sees the run fail
  assert.equal(endedAt, t0);
  endedAt = seenFinishedAt("failed", endedAt, t0 + 5_000); // still finished: the first sighting stands
  assert.equal(endedAt, t0);
  endedAt = seenFinishedAt("running", endedAt, t0 + 20_000); // Retry node: the run runs again
  assert.equal(endedAt, undefined);
  assert.equal(reportNext(false, endedAt, t0 + REPORT_WAIT_MS + 1), "wait"); // past the first bound, but no bound while it runs
  endedAt = seenFinishedAt("failed", endedAt, t0 + 100_000); // it ends again
  assert.equal(reportNext(false, endedAt, t0 + 100_000 + REPORT_WAIT_MS - 1), "wait"); // the bound counts from this end
  assert.equal(reportNext(false, endedAt, t0 + 100_000 + REPORT_WAIT_MS), "gone");
  for (const s of ["pending", "provisioning_gpu", "running"] as const) assert.equal(seenFinishedAt(s, t0, t0 + 1), undefined, s);
  for (const s of ["succeeded", "failed", "cancelled"] as const) assert.equal(seenFinishedAt(s, undefined, t0), t0, s);
});

test("the report's first line, ## <plan>: <status>, is its title; the rest stays Markdown as written", () => {
  assert.deepEqual(splitReport("## movies: succeeded\n\n**Intent:** x\n\n## Cost\n$0"), { title: "movies: succeeded", body: "**Intent:** x\n\n## Cost\n$0" });
  assert.deepEqual(splitReport("## only a title"), { title: "only a title", body: "" });
  assert.deepEqual(splitReport("no title\n## Cost"), { title: null, body: "no title\n## Cost" }); // only the first line is the title
  assert.equal(splitReport("### Cost\nx").title, null); // and only `## `, the level the API writes
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
