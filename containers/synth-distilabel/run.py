"""containers/synth-distilabel/run.py — KAN-10 (Nebius x NVIDIA Hackathon edition)

CPU node. Generates synthetic ChatML rows via a teacher LLM.
Three pipeline templates: Self-Instruct, Evol-Instruct, Magpie.

Teacher priority:
  1. NVIDIA Nemotron Super 49B via Nebius Token Factory (default, if NEBIUS_API_KEY set)
  2. OpenAI (if OPENAI_API_KEY set)
  3. Anthropic (if ANTHROPIC_API_KEY set)
  4. Stub mode — deterministic completions keyed on sha256(prompt), no API key needed

Stub mode: always active when no API key is available. Emits deterministic
synthetic rows so the full pipeline is exercisable without credentials.

Inputs (ORCHAPOD_NODE_INPUTS):
  pipeline_template  — "self-instruct" | "evol-instruct" | "magpie"
  teacher_kind       — "nebius" | "openai" | "anthropic"  (default: "nebius")
  teacher_model      — model ID (default: nvidia/nemotron-3-super-120b-a12b)
  n_samples          — number of rows to generate (default: 1000)
  seed_prompts       — R2 URI to seed prompts JSONL (optional)
  temperature        — sampling temperature (default: 0.8)
  max_tokens         — max output tokens per call (default: 512)

Outputs: dataset, cost_summary_json
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from orchapod import io, log


_NEBIUS_API_BASE = "https://api.studio.nebius.ai/v1"
_DEFAULT_TEACHER_MODEL = "nvidia/nemotron-3-super-120b-a12b"

_PRICING_USD_PER_M_TOKENS = {
    "nebius":    {"input": 0.18, "output": 0.60},   # Nemotron Super 49B Token Factory pricing
    "openai":    {"input": 0.15, "output": 0.60},   # gpt-4o-mini
    "anthropic": {"input": 0.80, "output": 4.00},   # claude-3-5-haiku
}

_EVOLUTION_PROMPTS = (
    "Rewrite the following instruction so it requires deeper reasoning. Add one "
    "constraint that forces multi-step thought. Output ONLY the new instruction.",
    "Rewrite the following instruction to broaden its scope to a related domain. "
    "Output ONLY the new instruction.",
    "Add a precision constraint to the following instruction (units, format, length). "
    "Output ONLY the new instruction.",
)

_MAGPIE_TOPICS = (
    "AI model training", "data preprocessing", "scientific reasoning",
    "code optimization", "math problem solving", "logical inference",
    "creative writing", "summarization", "question answering",
)


# ---------------------------------------------------------------------------
# Stub mode helpers
# ---------------------------------------------------------------------------

def _stub_completion(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    return f"[stub completion {digest}]"


def _is_stub(teacher_kind: str, api_key: str | None) -> bool:
    stub_env = os.environ.get("STUB_TEACHER", "").lower() in ("1", "true", "yes")
    if stub_env:
        return True
    return not api_key


# ---------------------------------------------------------------------------
# Teacher implementations
# ---------------------------------------------------------------------------

class TeacherCall:
    in_tokens: int = 0
    out_tokens: int = 0

    def __init__(self, kind: str, model: str, api_key: str | None, *, stub: bool):
        self.kind = kind
        self.model = model
        self.api_key = api_key
        self.stub = stub

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        if self.stub:
            return _stub_completion(prompt)

        if self.kind == "nebius":
            return self._nebius(prompt, temperature, max_tokens)
        elif self.kind == "openai":
            return self._openai(prompt, temperature, max_tokens)
        elif self.kind == "anthropic":
            return self._anthropic(prompt, temperature, max_tokens)
        raise ValueError(f"Unknown teacher_kind={self.kind!r}")

    def _nebius(self, prompt: str, temperature: float, max_tokens: int) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(
            f"{_NEBIUS_API_BASE}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        usage = resp.get("usage", {})
        self.in_tokens  += usage.get("prompt_tokens", 0)
        self.out_tokens += usage.get("completion_tokens", 0)
        return resp["choices"][0]["message"]["content"]

    def _openai(self, prompt: str, temperature: float, max_tokens: int) -> str:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.in_tokens  += resp.usage.prompt_tokens
        self.out_tokens += resp.usage.completion_tokens
        return resp.choices[0].message.content

    def _anthropic(self, prompt: str, temperature: float, max_tokens: int) -> str:
        from anthropic import Anthropic  # type: ignore
        client = Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        self.in_tokens  += resp.usage.input_tokens
        self.out_tokens += resp.usage.output_tokens
        return resp.content[0].text


# ---------------------------------------------------------------------------
# Pipeline templates
# ---------------------------------------------------------------------------

def _row(instruction: str, completion: str, template: str) -> dict:
    return {
        "messages": [
            {"role": "user",      "content": instruction},
            {"role": "assistant", "content": completion},
        ],
        "_meta": {"source": f"synth-distilabel/{template}"},
    }


def run_self_instruct(teacher: TeacherCall, seed_prompts: list[str],
                      n_samples: int, temperature: float, max_tokens: int) -> list[dict]:
    rows = []
    batch_size = 8
    per_call = max(1, n_samples // batch_size + 1)
    while len(rows) < n_samples:
        remaining = n_samples - len(rows)
        k = min(batch_size, remaining)
        examples = "\n".join(f"- {p}" for p in seed_prompts[:3]) if seed_prompts else "- Explain a concept in plain language."
        prompt = (
            f"Write {k} NEW diverse instructions for an AI assistant. "
            f"Each must be a complete standalone question or task. "
            f"Inspired by (but different from):\n{examples}\n"
            f"Output ONLY a JSON array of strings."
        )
        raw = teacher.generate(prompt, temperature, max_tokens)
        try:
            import re
            m = re.search(r"\[.*?\]", raw, re.DOTALL)
            instructions = json.loads(m.group()) if m else []
        except Exception:
            instructions = [raw.strip()] if raw.strip() else []
        for instr in instructions[:remaining]:
            completion = teacher.generate(instr, temperature, max_tokens)
            rows.append(_row(instr, completion, "self-instruct"))
            if len(rows) >= n_samples:
                break
    return rows[:n_samples]


def run_evol_instruct(teacher: TeacherCall, seed_prompts: list[str],
                      n_samples: int, temperature: float, max_tokens: int) -> list[dict]:
    import random
    rows = []
    seeds = list(seed_prompts) if seed_prompts else [
        "What is machine learning?", "Explain attention mechanisms.",
        "How does gradient descent work?",
    ]
    while len(rows) < n_samples:
        seed = random.choice(seeds)
        evol_prompt = random.choice(_EVOLUTION_PROMPTS) + f"\n\nOriginal: {seed}"
        evolved = teacher.generate(evol_prompt, 0.9, 256) or ""
        if not evolved.strip():
            continue
        completion = teacher.generate(evolved, temperature, max_tokens) or ""
        rows.append(_row(evolved, completion, "evol-instruct"))
    return rows[:n_samples]


def run_magpie(teacher: TeacherCall, n_samples: int,
               temperature: float, max_tokens: int) -> list[dict]:
    import random
    rows = []
    while len(rows) < n_samples:
        topic = random.choice(_MAGPIE_TOPICS)
        instr_prompt = (
            f"Invent a realistic question or task about '{topic}' that a user might ask an AI assistant. "
            f"Output ONLY the question/task, nothing else."
        )
        instruction = teacher.generate(instr_prompt, temperature, 150) or ""
        if not instruction.strip():
            continue
        completion  = teacher.generate(instruction, temperature, max_tokens) or ""
        rows.append(_row(instruction.strip(), completion, "magpie"))
    return rows[:n_samples]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    inputs = io.read_inputs()
    log.info("synth-distilabel starting")

    template     = inputs.get("pipeline_template", "self-instruct")
    teacher_kind = inputs.get("teacher_kind", "nebius")
    teacher_model = inputs.get("teacher_model", _DEFAULT_TEACHER_MODEL)
    n_samples    = int(inputs.get("n_samples", 1000))
    seed_uri     = inputs.get("seed_prompts")
    temperature  = float(inputs.get("temperature", 0.8))
    max_tokens   = int(inputs.get("max_tokens", 512))

    # Resolve API key: check NEBIUS_API_KEY first for nebius kind
    if teacher_kind == "nebius":
        api_key = os.environ.get("NEBIUS_API_KEY")
    elif teacher_kind == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
    elif teacher_kind == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    else:
        api_key = None

    stub = _is_stub(teacher_kind, api_key)
    if stub:
        log.info(f"synth-distilabel: STUB MODE (teacher_kind={teacher_kind!r}, no API key)")
    else:
        log.info(f"synth-distilabel: teacher={teacher_kind}/{teacher_model}")

    teacher = TeacherCall(teacher_kind, teacher_model, api_key, stub=stub)

    # Load seed prompts if provided
    seed_prompts: list[str] = []
    if seed_uri:
        seed_path = io.download_input(seed_uri, "/workspace/seeds")
        with open(seed_path) as f:
            for line in f:
                row = json.loads(line)
                seed_prompts.append(row.get("prompt", row.get("instruction", str(row))))

    log.info(f"Generating {n_samples} rows via {template}")

    if template == "self-instruct":
        rows = run_self_instruct(teacher, seed_prompts, n_samples, temperature, max_tokens)
    elif template == "evol-instruct":
        rows = run_evol_instruct(teacher, seed_prompts, n_samples, temperature, max_tokens)
    elif template == "magpie":
        rows = run_magpie(teacher, n_samples, temperature, max_tokens)
    else:
        raise ValueError(f"Unknown pipeline_template={template!r}")

    log.info(f"Generated {len(rows)} rows")

    # Write dataset
    dataset_path = io.local_path("dataset.jsonl")
    with open(dataset_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # Cost summary
    pricing = _PRICING_USD_PER_M_TOKENS.get(teacher_kind, {"input": 0, "output": 0})
    cost_usd = (
        teacher.in_tokens  / 1_000_000 * pricing["input"] +
        teacher.out_tokens / 1_000_000 * pricing["output"]
    )
    cost_data = {
        "teacher":       f"{teacher_kind}/{teacher_model}",
        "stubbed":       stub,
        "in_tokens":     teacher.in_tokens,
        "out_tokens":    teacher.out_tokens,
        "cost_usd":      round(cost_usd, 4),
        "n_rows":        len(rows),
        "template":      template,
    }
    cost_path = io.local_path("cost_summary.json")
    with open(cost_path, "w") as f:
        json.dump(cost_data, f, indent=2)

    io.write_output("dataset",           dataset_path, kind="dataset")
    io.write_output("cost_summary_json", cost_path,    kind="metrics")

    log.info(f"Done. Cost: ${cost_usd:.4f} ({teacher.in_tokens}in + {teacher.out_tokens}out tokens)")
    if stub:
        log.info("NOTE: stub mode — set NEBIUS_API_KEY for real Nemotron-generated data")


if __name__ == "__main__":
    main()
