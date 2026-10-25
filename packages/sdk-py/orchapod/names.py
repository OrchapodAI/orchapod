"""
packages/sdk-py/orchapod/names.py

Names the control plane and the nodes must agree on: both images ship this package.
"""

import re


def endpoint_name(run_id: str, node_id: str) -> str:
    """The Nebius Serverless Endpoint of a vllm-serve node: one per node of a run (R19), unique per project. The node
    creates its endpoint under this name, and the API finds the endpoint by it while the node runs, before the node has
    registered an id."""
    return re.sub(r"[^a-z0-9-]+", "-", f"orchapod-{run_id[:8]}-{node_id}".lower())[:63].strip("-")
