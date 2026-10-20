"""Tavily client against recorded Tavily REST responses (no live calls)."""

from __future__ import annotations

import json

import httpx
import pytest

from packages.providers.base import ProviderError
from packages.providers.tavily import Tavily


def recorder():
    calls = []
    return calls, lambda *a, **k: calls.append((a, k))


def test_search_sends_usage_flag_and_bills_credits(replay):
    calls, on_usage = recorder()
    hit = {"url": "https://www.hud.gov/fair-housing", "title": "Fair Housing Act", "content": "The Act ...", "score": 0.91}
    http, seen = replay(httpx.Response(200, json={"query": "fair housing act", "results": [hit],
                                                  "response_time": 1.2, "usage": {"credits": 2}}))
    out = Tavily(on_usage=on_usage, http=http).search("fair housing act", max_results=5, include_domains=["hud.gov"])
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.tavily.com/search"
    assert seen[0].headers["authorization"] == "Bearer tvly-key"
    assert body == {"query": "fair housing act", "search_depth": "advanced", "max_results": 5,
                    "include_raw_content": False, "include_domains": ["hud.gov"], "include_usage": True}
    assert out["results"] == [hit]
    assert calls == [(("tavily", "search"), {"credits": 2, "usd": pytest.approx(0.016)})]


def test_extract_goes_out_in_batches_of_20_and_merges(replay):
    calls, on_usage = recorder()
    urls = [f"https://example.org/{i}" for i in range(45)]

    def batch(urls_in, credits):
        return httpx.Response(200, json={"results": [{"url": u, "raw_content": "text"} for u in urls_in[1:]],
                                         "failed_results": [{"url": urls_in[0], "error": "timeout"}],
                                         "usage": {"credits": credits}})
    http, seen = replay(batch(urls[:20], 4), batch(urls[20:40], 4), batch(urls[40:], 1))
    out = Tavily(on_usage=on_usage, http=http).extract(urls)
    assert [len(json.loads(r.content)["urls"]) for r in seen] == [20, 20, 5]
    assert json.loads(seen[0].content)["extract_depth"] == "basic"
    assert len(out["results"]) == 42 and [f["url"] for f in out["failed_results"]] == [urls[0], urls[20], urls[40]]
    assert [k["credits"] for _, k in calls] == [4, 4, 1]


@pytest.mark.parametrize("status", [432, 433])
def test_plan_limits_are_quota_and_not_retried(replay, status):
    http, seen = replay(httpx.Response(status, json={"detail": {"error": "This request exceeds your plan's set usage limit."}}))
    with pytest.raises(ProviderError) as e:
        Tavily(http=http).search("q")
    assert (e.value.kind, len(seen)) == ("quota", 1)


def test_missing_key_is_auth_error_before_send(replay, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY")
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        Tavily(http=http).search("q")
    assert e.value.kind == "auth" and seen == []


def test_stub_is_deterministic_and_offline(monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("TAVILY_API_KEY")
    calls, on_usage = recorder()
    a = Tavily(on_usage=on_usage).search("fair housing act", max_results=3, include_raw_content=True)
    assert a == Tavily().search("fair housing act", max_results=3, include_raw_content=True)
    urls = [r["url"] for r in a["results"]]
    assert len(urls) == 3 and all(u.startswith("https://example.com/stub/") for u in urls) and len(set(urls)) == 3
    assert all(len(r["raw_content"]) >= 400 for r in a["results"])
    assert Tavily().search("other", max_results=3)["results"][0]["url"] != urls[0]
    pages = Tavily().extract(["https://a.example/x", "https://b.example/y"])["results"]
    assert [p["url"] for p in pages] == ["https://a.example/x", "https://b.example/y"]
    assert all(len(p["raw_content"]) >= 400 for p in pages) and pages[0]["raw_content"] != pages[1]["raw_content"]
    assert calls == [(("tavily", "search"), {"credits": 0, "usd": 0.0})]
