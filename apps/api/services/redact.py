"""
apps/api/services/redact.py

R10: tokens never reach artifact meta or the browser. Meta comes from nodes, and a node can put a key in it (the old
vllm-serve writes {"api_key": ...}), so the API redacts secret-looking keys where meta comes in (/internal/artifact) and
wherever it goes out (run summary and report, artifact lists, the golden-run export).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"
# words of the key, after camelCase (acronyms too: HFToken → hf_token) and kebab-case become snake_case; token only as
# the last word (token_factory and token_count are names and counts)
_SECRET = re.compile(r"(?:^|_)(?:api_?key|access_?key|secret|password|authorization)(?:_|$)|(?:^|_)token$")
_WORDS = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def redact(value):
    """`value` with the value of every secret-looking key replaced, in nested dicts and lists too. A key ending in _env
    whose value is an env var's name (a ModelRef's api_key_env) stays; counts such as max_tokens do not match."""
    if isinstance(value, dict):
        return {k: REDACTED if _secret(k, v) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


# `key=value`, `key: value` or `"key": "value"` in free text. A key starts only at a word's start; the value may follow an
# auth scheme (Authorization: Bearer abc) and ends at a space, quote, comma, semicolon, & or }.
_PAIR = re.compile(r"""(?<![\w.-])([\w.-]+)(["']?\s*[:=]\s*["']?)((?:(?i:bearer|basic)\s+)?[^\s"',;&}]+)""")
# a token no key names ("sent Bearer eyJ…"): it has a digit, + / =, or a capital after its first character, so prose such as
# "basic configuration" stays readable
_BEARER = re.compile(r"\b((?i:bearer|basic))\s+(?=[\w.~+/=-]*?(?:[0-9+/=]|(?<=[\w.~+/=-])[A-Z]))[\w.~+/=-]{8,}")
_USERINFO = re.compile(r"(?<=://)[^/\s@:]*:[^/\s@]+(?=@)")  # the user:password of https://user:pw@host/


def redact_text(text: str) -> str:
    """`text` (a log line is free text, which redact() cannot walk) with every secret in it replaced: the value of a
    secret-looking pair, by redact()'s key rule (NEBIUS_API_KEY=sk-1 and "api_key": "sk-1" lose the value, max_tokens=512 does
    not), also one inside another value (`ValueError: api_key=…`, `?token=…` in a URL); a Bearer or Basic token; the
    user:password of a URL. A scan, not a recursion. Quadratic in the worst case (a line of nothing but pairs: 6 ms at 2,000
    characters, 1.4 s at 32,000), which is why logs.clean() cuts a line first."""
    out, last, pos = [], 0, 0
    while m := _PAIR.search(text, pos):
        if _secret(m[1], m[3]):
            out += [text[last:m.start(3)], REDACTED]
            last = pos = m.end()
        else:
            pos = m.start(3)  # its value may hold a pair of its own
    text = "".join(out) + text[last:]
    return _USERINFO.sub(REDACTED, _BEARER.sub(lambda m: f"{m[1]} {REDACTED}", text))


def without_secrets(spec):
    """A workflow spec (parsed YAML or a plan) without the node inputs whose key looks like a secret, by the same rule:
    stored, a token would reach the database, the canvas graph, every run's inputs and the UI. Dropped, not redacted, so
    a node never gets "[redacted]" as a value; nodes take their keys from the executor's env."""
    if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list):
        return spec
    return {**spec, "nodes": [{**n, "inputs": _drop(n["inputs"])}
                              if isinstance(n, dict) and isinstance(n.get("inputs"), dict) else n for n in spec["nodes"]]}


def _drop(value):
    """`value` without its secret-looking keys, in nested dicts and lists too (a token pasted under cfg: or headers:)."""
    if isinstance(value, dict):
        return {k: _drop(v) for k, v in value.items() if not _secret(k, v)}
    if isinstance(value, list):
        return [_drop(v) for v in value]
    return value


def _secret(key, value) -> bool:
    k = _WORDS.sub("_", str(key)).lower().replace("-", "_")
    if k.endswith("_env"):
        if isinstance(value, str) and _ENV_NAME.fullmatch(value):
            return False  # it names where the secret is, not the secret
        k = k.removesuffix("_env")
    return bool(_SECRET.search(k))
