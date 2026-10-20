"""
apps/api/agent/workflow_builder.py

Agent layer — "build a workflow from a natural-language prompt."
Uses Claude Sonnet via Anthropic API with tool use.

MVP scope:
  - Agent DRAFTS the workflow YAML. It does NOT execute it.
  - Execution authority stays with the user clicking Run.
  - This matches the Claude Code "propose-then-approve" pattern.

Tools available to the agent:
  - list_node_types()     → returns the 7 node types + their schemas
  - validate_workflow()   → checks DAG correctness, returns errors or "valid"

Implementation effort: ~2 days
"""

from __future__ import annotations
import json
import anthropic

from packages.workflow_schema.models import NODE_REGISTRY


SYSTEM_PROMPT = """
You are an ML workflow architect for Orchapod.ai.
The user describes a fine-tuning goal; you produce a valid workflow YAML.

Available node types: data-prep, unsloth-train, distill-sft, quantize, lm-eval, vllm-serve

Rules:
- Always start with a data-prep node unless the user explicitly says to skip it
- If the user mentions "distill" or "smaller model", include distill-sft after unsloth-train
- If the user mentions "Ollama" or "local" or "GGUF", include a quantize node with method=gguf
- If the user mentions "serve", "endpoint", or "API", end with vllm-serve
- Always include lm-eval before vllm-serve unless the user explicitly skips evaluation
- Default base model: Qwen/Qwen3-4B-Instruct (unless user specifies another)
- Default student model for distillation: Qwen/Qwen3-1.7B-Instruct

Use the list_node_types tool to check available schemas.
Use the validate_workflow tool to verify your draft before responding.
Return ONLY the YAML inside a ```yaml ... ``` code block. No prose before or after.
""".strip()


# ---------------------------------------------------------------------------
# Tool definitions (passed to Claude API)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_node_types",
        "description": "Returns the available node types and their input/output schemas.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "validate_workflow",
        "description": "Validates a workflow YAML string. Returns 'valid' or a list of errors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml": {
                    "type": "string",
                    "description": "The workflow YAML to validate.",
                }
            },
            "required": ["yaml"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _list_node_types() -> str:
    result = {}
    for node_type, meta in NODE_REGISTRY.items():
        schema = meta["inputs_schema"].model_json_schema()
        result[node_type.value] = {
            "description": meta["description"],
            "inputs": {
                k: v for k, v in schema.get("properties", {}).items()
            },
        }
    return json.dumps(result, indent=2)


def _validate_workflow(yaml_str: str) -> str:
    from apps.api.executor.dag import compile_dag
    try:
        dag = compile_dag(yaml_str, {})
        order = dag.topological_order()
        return f"valid — {len(order)} nodes in order: {[n.id for n in order]}"
    except Exception as e:
        return f"error: {e}"


def _handle_tool_call(tool_name: str, tool_input: dict) -> str:
    if tool_name == "list_node_types":
        return _list_node_types()
    elif tool_name == "validate_workflow":
        return _validate_workflow(tool_input["yaml"])
    return f"unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

async def build_workflow_from_prompt(prompt: str, api_key: str) -> str:
    """
    Given a natural-language prompt, return a workflow YAML string.
    Raises ValueError if the agent cannot produce a valid workflow.
    """
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": prompt}]

    # Agentic loop — Claude may call tools multiple times before returning YAML
    for _ in range(5):  # max 5 iterations
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # If Claude called tools, run them and loop
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Claude returned a text response — extract YAML
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        yaml_str = _extract_yaml(text)
        if yaml_str:
            return yaml_str

        raise ValueError(f"Agent did not return a YAML block. Response: {text[:500]}")

    raise ValueError("Agent exceeded maximum iterations without producing a workflow.")


def _extract_yaml(text: str) -> str | None:
    """Extract the content of a ```yaml ... ``` block."""
    import re
    match = re.search(r"```ya?ml\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
