"""
apps/api/services/redact.py

R10: tokens never reach artifact meta or the browser. Meta comes from nodes, and a node can put a key in it (the old
vllm-serve writes {"api_key": ...}), so the API redacts secret-looking keys where meta comes in (/internal/artifact) and
wherever it goes out (run summary and report, artifact lists, the golden-run export).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"
# a word of the key, after camelCase and kebab-case become snake_case
_SECRET = re.compile(r"(?:^|_)(?:api_?key|token|secret|password|authorization)(?:_|$)")


def redact(value):
    """`value` with the value of every secret-looking key replaced, in nested dicts and lists too. A key ending in _env
    names an env var (a ModelRef's api_key_env) and stays; counts such as max_tokens do not match."""
    if isinstance(value, dict):
        return {k: REDACTED if _secret(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _secret(key) -> bool:
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).lower().replace("-", "_")
    return not k.endswith("_env") and bool(_SECRET.search(k))
