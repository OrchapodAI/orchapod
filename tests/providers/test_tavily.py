"""Tavily client against recorded Tavily REST responses (no live calls)."""

from __future__ import annotations

import json

import httpx
import pytest

from packages.providers.base import ProviderError
from packages.providers.tavily import Tavily


def test_search_sends_usage_flag_and_bills_credits(replay, recorder):
    calls, on_usage = recorder
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


def test_extract_goes_out_in_batches_of_20_and_merges(replay, recorder):
    calls, on_usage = recorder
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


def answer_without_usage(n_ok, n_failed=0):
    return httpx.Response(200, json={"results": [{"url": f"https://x.example/{i}", "raw_content": "text"} for i in range(n_ok)],
                                     "failed_results": [{"url": "https://x.example/gone", "error": "404"}] * n_failed})


@pytest.mark.parametrize("call,credits", [
    (lambda t: t.search("q"), 2),  # advanced, the default
    (lambda t: t.search("q", search_depth="basic"), 1),
    (lambda t: t.extract(["u"] * 8), 2),  # basic: 1 per 5 successful URLs (7 of 8 succeed); failed ones are free
    (lambda t: t.extract(["u"] * 8, extract_depth="advanced"), 4),
], ids=["search_advanced", "search_basic", "extract_basic", "extract_advanced"])
def test_missing_usage_falls_back_to_the_credit_rule(replay, recorder, call, credits):
    calls, on_usage = recorder
    http, _ = replay(answer_without_usage(7, 1))
    call(Tavily(on_usage=on_usage, http=http))
    assert calls[0][1] == {"credits": credits, "usd": pytest.approx(credits * 0.008)}


@pytest.mark.parametrize("status", [432, 433])
def test_plan_limits_are_quota_and_not_retried(replay, status):
    http, seen = replay(httpx.Response(status, json={"detail": {"error": "This request exceeds your plan's set usage limit."}}))
    with pytest.raises(ProviderError) as e:
        Tavily(http=http).search("q")
    assert (e.value.kind, len(seen)) == ("quota", 1)


def test_a_2xx_reply_that_is_not_json_is_bad_output_not_retried(replay, recorder):
    calls, on_usage = recorder
    http, seen = replay(httpx.Response(200, text="<html>gateway</html>"))
    with pytest.raises(ProviderError) as e:
        Tavily(on_usage=on_usage, http=http).search("q")
    assert (e.value.kind, len(seen), calls) == ("bad_output", 1, [])


def test_missing_key_is_auth_error_before_send(replay, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY")
    http, seen = replay()
    with pytest.raises(ProviderError) as e:
        Tavily(http=http).search("q")
    assert e.value.kind == "auth" and seen == []


def test_stub_is_deterministic_and_offline(monkeypatch, recorder, replay):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("TAVILY_API_KEY")
    calls, on_usage = recorder
    a = Tavily(on_usage=on_usage).search("fair housing act", max_results=3, include_raw_content=True)
    assert a == Tavily().search("fair housing act", max_results=3, include_raw_content=True)
    urls = [r["url"] for r in a["results"]]
    assert len(urls) == 3 and all(u.startswith("https://example.com/stub/") for u in urls) and len(set(urls)) == 3
    assert all(len(r["raw_content"]) >= 400 for r in a["results"])
    assert Tavily().search("other", max_results=3)["results"][0]["url"] != urls[0]
    http, seen = replay()
    assert Tavily(http=http).search("fair housing act", max_results=3, include_raw_content=True) == a and seen == []
    pages = Tavily().extract(["https://a.example/x", "https://b.example/y"])["results"]
    assert [p["url"] for p in pages] == ["https://a.example/x", "https://b.example/y"]
    assert all(len(p["raw_content"]) >= 400 for p in pages) and pages[0]["raw_content"] != pages[1]["raw_content"]
    assert calls == [(("tavily", "search"), {"credits": 0, "usd": 0.0})]
