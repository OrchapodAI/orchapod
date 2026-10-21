"""
apps/api/services/redact.py

R10: tokens never reach artifact meta or the browser. Meta comes from nodes, and a node can put a key in it (the old
vllm-serve writes {"api_key": ...}), so the API redacts secret-looking keys where meta comes in (/internal/artifact) and
wherever it goes out (run summary and report, artifact lists, the golden-run export).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"
# words of the key, after camelCase and kebab-case become snake_case; token only as the last word (token_factory and
# token_count are names and counts)
_SECRET = re.compile(r"(?:^|_)(?:api_?key|secret|password|authorization)(?:_|$)|(?:^|_)token$")
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def redact(value):
    """`value` with the value of every secret-looking key replaced, in nested dicts and lists too. A key ending in _env
    whose value is an env var's name (a ModelRef's api_key_env) stays; counts such as max_tokens do not match."""
    if isinstance(value, dict):
        return {k: REDACTED if _secret(k, v) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def without_secrets(spec):
    """A workflow spec (parsed YAML or a plan) without the node inputs whose key looks like a secret, by the same rule:
    stored, a token would reach the database, the canvas graph, every run's inputs and the UI. Dropped, not redacted, so
    a node never gets "[redacted]" as a value; nodes take their keys from the executor's env."""
    if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list):
        return spec
    return {**spec, "nodes": [{**n, "inputs": {k: v for k, v in n["inputs"].items() if not _secret(k, v)}}
                              if isinstance(n, dict) and isinstance(n.get("inputs"), dict) else n for n in spec["nodes"]]}


def _secret(key, value) -> bool:
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).lower().replace("-", "_")
    if k.endswith("_env"):
        if isinstance(value, str) and _ENV_NAME.fullmatch(value):
            return False  # it names where the secret is, not the secret
        k = k.removesuffix("_env")
    return bool(_SECRET.search(k))
