"""
apps/api/services/nebius_token_factory.py

Nebius Token Factory — OpenAI-compatible inference API backed by NVIDIA Nemotron models.

Base URL:  https://api.studio.nebius.ai/v1
Auth:      Bearer NEBIUS_API_KEY
Docs:      https://studio.nebius.ai/

Available Nemotron models via Token Factory (verified 2026-10-08):
  nvidia/Nemotron-3-Ultra-550b-a55b    → "Ultra"     — highest reasoning quality (judge)
  nvidia/nemotron-3-super-120b-a12b    → "Super"     — fast, balanced (teacher / general)
  nvidia/Nemotron-3_5-Lightning        → "Lightning" — fastest
  nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B → "Nano"    — edge / low-latency

Usage:
  from api.services.nebius_token_factory import token_factory
  resp = await token_factory.chat([{"role": "user", "content": "Hello"}])
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx

_BASE_URL = "https://api.studio.nebius.ai/v1"

# Token Factory model IDs (verified against api.studio.nebius.ai/v1/models 2026-10-08)
NEMOTRON_ULTRA     = "nvidia/Nemotron-3-Ultra-550b-a55b"       # best judge / reasoning
NEMOTRON_SUPER     = "nvidia/nemotron-3-super-120b-a12b"       # teacher / general
NEMOTRON_LIGHTNING = "nvidia/Nemotron-3_5-Lightning"           # fastest
NEMOTRON_NANO      = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"   # edge

# All models available via Token Factory
TOKEN_FACTORY_MODELS = [NEMOTRON_ULTRA, NEMOTRON_SUPER, NEMOTRON_LIGHTNING, NEMOTRON_NANO]


def _api_key() -> str | None:
    return os.environ.get("NEBIUS_API_KEY")


def is_available() -> bool:
    """True when NEBIUS_API_KEY is set."""
    return bool(_api_key())


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        raise RuntimeError(
            "NEBIUS_API_KEY is not set. "
            "Get your key at https://studio.nebius.ai → API Keys."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def chat(
    messages: list[dict],
    model: str = NEMOTRON_SUPER,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> str:
    """
    Single chat completion via Nebius Token Factory.
    Returns the assistant message content string.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def stream_chat(
    messages: list[dict],
    model: str = NEMOTRON_SUPER,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """
    Streaming chat completion — yields text chunks as they arrive.
    Compatible with the TryItChat SSE reader in the frontend.
    """
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                import json
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except (KeyError, json.JSONDecodeError):
                    pass


async def judge_response(
    prompt: str,
    model_response: str,
    reference_answer: str | None = None,
    judge_model: str = NEMOTRON_ULTRA,
) -> dict:
    """
    Use Nemotron Ultra as an LLM judge to score a model response.
    Returns {"score": float [0-1], "reasoning": str, "verdict": str}.

    This replaces the Anthropic/Claude judge in lm-eval so the entire
    evaluation pipeline runs on NVIDIA open-source models via Nebius.
    """
    ref_line = (
        f"\nReference answer: {reference_answer}" if reference_answer else ""
    )
    system_prompt = (
        "You are an expert evaluator. Score the given response on a scale of 0.0 to 1.0 "
        "for correctness, helpfulness, and quality. "
        "Respond with valid JSON only: {\"score\": <float>, \"verdict\": \"<pass|fail>\", \"reasoning\": \"<one line>\"}"
    )
    user_msg = (
        f"Prompt: {prompt}\n"
        f"Response: {model_response}"
        f"{ref_line}"
    )
    raw = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        model=judge_model,
        temperature=0.0,
        max_tokens=256,
    )
    import json
    import re
    # Extract JSON even if the model wraps it in markdown fences
    m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"score": 0.5, "verdict": "unknown", "reasoning": raw[:200]}
