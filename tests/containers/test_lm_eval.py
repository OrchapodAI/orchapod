"""
Unit tests for containers/lm-eval/run.py: Nemotron on Token Factory is the only judge (no Claude fallback).
"""

import io
import json
from pathlib import Path
from unittest.mock import patch

from .conftest import load_container

lm = load_container("lm-eval")
ROW = [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}]


def test_anthropic_key_alone_does_not_start_a_judge(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch.object(lm.subprocess, "Popen", side_effect=AssertionError("ran a judge on ANTHROPIC_API_KEY")):
        out = lm.run_llm_judge(Path("model"), ROW, "judge")
    assert (out["judge"], out["n_prompts"]) == ("none", 0)


def test_nebius_judge_still_scores(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "nk-test")
    urls = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"score": 4, "reason": "ok"}'}}]}).encode())

    with patch.object(lm.subprocess, "Popen"), patch.object(lm, "_wait_for_server"), \
         patch.object(lm.urllib.request, "urlopen", urlopen):
        out = lm.run_llm_judge(Path("model"), ROW, "nvidia/Nemotron-3-Ultra-550b-a55b")
    assert (out["judge"], out["avg_score"], out["n_prompts"]) == ("nemotron:Nemotron-3-Ultra-550b-a55b", 4, 1)
    assert any("nebius" in u for u in urls)


def test_image_ships_no_anthropic_sdk():
    dockerfile = Path(__file__).resolve().parents[2] / "containers/lm-eval/Dockerfile"
    assert "anthropic" not in dockerfile.read_text().lower()
