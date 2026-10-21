import type { Edge, Node } from "@xyflow/react";
import type { OrchaNodeData } from "../components/canvas/OrchaNode";
import type { Plan, PlanNode } from "./types";

// Strings a plain YAML scalar would lose or misread: empty, multi-line, "key: value", " #comment",
// edge spaces, a leading indicator. Flow syntax ("[a, b]", "{...}") stays plain on purpose.
const NEEDS_QUOTES = /^$|^\s|\s$|\n|:\s|:$|\s#|^[#&*!|>%@`]|^[-?:](\s|$)/;

/** A YAML value. JSON is YAML flow syntax, so objects and lists (R13) and risky strings go out as JSON. */
export function yamlValue(v: unknown): string {
  if (typeof v === "string") return NEEDS_QUOTES.test(v) ? JSON.stringify(v) : v;
  return v !== null && typeof v === "object" ? JSON.stringify(v) : String(v);
}

function nodesYaml(nodes: PlanNode[]): string[] {
  return nodes.flatMap(({ id, type, needs = [], inputs = {} }) => [
    `  - id: ${id}`,
    `    type: ${type}`,
    ...(needs.length > 0 ? [`    needs: [${needs.join(", ")}]`] : []),
    Object.keys(inputs).length > 0 ? "    inputs:" : "    inputs: {}",
    ...Object.entries(inputs).map(([k, v]) => `      ${k}: ${yamlValue(v)}`),
  ]);
}

/** An agent plan (docs/contracts.md "Agent API") as workflow YAML, for opening it on the canvas. */
export function planYaml(plan: Plan): string {
  return [`name: ${yamlValue(plan.name)}`, "nodes:", ...nodesYaml(plan.nodes)].join("\n");
}

/** The canvas graph as workflow YAML, keeping the existing header (name, version, inputs). */
export function buildYamlFromGraph(nodes: Node<OrchaNodeData>[], edges: Edge[], existingYaml: string): string {
  const lines = existingYaml.split("\n");
  const nodesIdx = lines.findIndex((l) => l.trimStart().startsWith("nodes:"));
  const header = nodesIdx >= 0 ? lines.slice(0, nodesIdx + 1) : [...lines, "nodes:"];
  return [
    ...header,
    ...nodesYaml(nodes.map((n) => ({
      id: n.data.label,
      type: n.data.node_type,
      needs: edges.filter((e) => e.target === n.id).map((e) => e.source),
      inputs: n.data.inputs ?? {},
    }))),
  ].join("\n");
}
