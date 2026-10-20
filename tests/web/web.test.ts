// Web unit tests. Run from the repo root: node --test "tests/web/*.test.ts"
// (Node >= 22.18 strips the types itself, so there is nothing to install.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { yamlValue, buildYamlFromGraph, planYaml } from "../../apps/web/lib/workflowYaml.ts";

const node = (id: string, node_type: string, inputs: Record<string, unknown>) =>
  ({ id, position: { x: 0, y: 0 }, data: { label: id, node_type, inputs, resources: {} } }) as never;

test("object and list inputs are written as JSON (R13)", () => {
  const rowSchema = { type: "object", properties: { action: { enum: ["like", "share"] } } };
  assert.equal(yamlValue(rowSchema), JSON.stringify(rowSchema));
  assert.equal(yamlValue({}), "{}");
  assert.equal(yamlValue(["Fair Housing Act", "RESPA"]), '["Fair Housing Act","RESPA"]');
});

test("strings a plain YAML scalar would misread are JSON-quoted; the rest stay plain", () => {
  for (const s of ["", "Audience: brokers", "see #3", "two\nlines", " padded", "*bold*", "- item"]) {
    assert.equal(yamlValue(s), JSON.stringify(s), s);
  }
  for (const s of ["16", "meta-llama/Llama-3.1-8B-Instruct", "${{ nodes.prep.outputs.train_jsonl }}", "https://a.io/x#y"]) {
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
