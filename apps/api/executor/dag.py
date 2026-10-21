"""
apps/api/executor/dag.py

DAG compiler — parses workflow YAML into a topologically ordered execution plan.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import yaml


@dataclass
class DAGNode:
    id: str
    type: str
    needs: list[str]
    inputs: dict[str, Any]
    resources: Any


@dataclass
class DAG:
    nodes: dict[str, DAGNode] = field(default_factory=dict)

    def topological_order(self) -> list[DAGNode]:
        """Kahn's algorithm — returns nodes in execution order."""
        in_degree = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.needs:
                in_degree[node.id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            nid = queue.pop(0)
            order.append(self.nodes[nid])
            for candidate in self.nodes.values():
                if nid in candidate.needs:
                    in_degree[candidate.id] -= 1
                    if in_degree[candidate.id] == 0:
                        queue.append(candidate.id)

        if len(order) != len(self.nodes):
            raise ValueError("Workflow YAML contains a cycle — DAGs must be acyclic.")

        return order


def load_yaml(text: str):
    """yaml.safe_load without aliases: a chain of a few hundred bytes (`&b [*a, *a, ...]`) expands to gigabytes once the
    spec is copied or serialised (graph_json, json.dumps), which would freeze the one API worker."""
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text, Loader=yaml.SafeLoader)):
        raise ValueError("workflow YAML may not use aliases (*name)")
    return yaml.safe_load(text)


def compile_dag(workflow_yaml: str, runtime_inputs: dict) -> DAG:
    """
    Parse a workflow YAML string into a DAG ready for execution.
    Validates node types, dependency references, and required inputs.
    """
    from packages.workflow_schema.models import NodeType  # noqa: PLC0415

    spec = load_yaml(workflow_yaml)
    dag = DAG()

    for node_spec in spec.get("nodes", []):
        node_type = node_spec["type"]
        if node_type not in [n.value for n in NodeType]:
            raise ValueError(f"Unknown node type: {node_type}")

        dag.nodes[node_spec["id"]] = DAGNode(
            id=node_spec["id"],
            type=node_type,
            needs=node_spec.get("needs", []),
            inputs=node_spec.get("inputs", {}),
            resources=node_spec.get("resources", {}),
        )

    # Validate all `needs` references exist
    for node in dag.nodes.values():
        for dep in node.needs:
            if dep not in dag.nodes:
                raise ValueError(f"Node '{node.id}' depends on '{dep}' which doesn't exist.")

    return dag


def workflow_to_graph_json(workflow_yaml: str) -> dict:
    """
    Convert workflow YAML to React Flow graph JSON for the canvas.
    Called on every save; YAML is source of truth, canvas derives from it.
    """
    dag = compile_dag(workflow_yaml, {})
    nodes = []
    edges = []

    positions = _auto_layout(dag)

    for node in dag.nodes.values():
        nodes.append({
            "id": node.id,
            "type": "orchapodNode",
            "position": positions[node.id],
            "data": {
                "node_type": node.type,
                "label": node.id,
                "inputs": node.inputs,
                "resources": node.resources,
            },
        })
        for dep in node.needs:
            edges.append({
                "id": f"{dep}->{node.id}",
                "source": dep,
                "target": node.id,
            })

    return {"nodes": nodes, "edges": edges}


def _auto_layout(dag: DAG) -> dict[str, dict]:
    """Simple left-to-right layout based on topological depth."""
    depth: dict[str, int] = {}
    for node in dag.topological_order():
        depth[node.id] = max((depth.get(d, 0) + 1 for d in node.needs), default=0)

    col_counts: dict[int, int] = {}
    positions = {}
    for node in dag.nodes.values():
        d = depth[node.id]
        row = col_counts.get(d, 0)
        col_counts[d] = row + 1
        positions[node.id] = {"x": d * 280, "y": row * 160}

    return positions
