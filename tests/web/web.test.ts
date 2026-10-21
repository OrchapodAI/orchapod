// Web unit tests. Run from the repo root: node --test "tests/web/*.test.ts"
// (Node >= 22.18 strips the types itself, so there is nothing to install.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { yamlValue, buildYamlFromGraph, planYaml } from "../../apps/web/lib/workflowYaml.ts";
import { api, explainError } from "../../apps/web/lib/api.ts";
import { defaultInputs } from "../../apps/web/lib/nodeForms.ts";

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
