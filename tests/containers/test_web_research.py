"""Unit tests for containers/web-research/run.py (docs/contracts.md "Data nodes → web-research")."""

import json
import re
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from orchapod import cost
from packages.providers.tavily import Tavily
from packages.workflow_schema.models import NODE_REGISTRY, NodeType, WebResearchInputs, WebResearchOutputs

from .conftest import load_container

wr = load_container("web-research")

ROOT = Path(__file__).resolve().parents[2]
METRIC_KEYS = {"queries", "urls", "urls_failed", "passages", "duplicates_dropped", "failed_calls"}


def para(ch: str, n: int) -> str:
    """About n chars of 9-letter words."""
    return " ".join([ch * 9] * (n // 10))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("STUB", "ORCHAPOD_MAX_COST_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-key")
    monkeypatch.setattr(cost, "_items", {})
    monkeypatch.setattr(time, "sleep", lambda s: None)  # the client's backoff


@pytest.fixture
def tavily(monkeypatch):
    """tavily(handler) -> [(path, body)] seen: the node's Tavily talks to `handler` in-process."""
    def install(handler):
        seen = []

        def record(request):
            seen.append((request.url.path, json.loads(request.content)))
            return handler(request)
        client = httpx.Client(transport=httpx.MockTransport(record))
        monkeypatch.setattr(wr, "Tavily", lambda **kw: Tavily(http=client, **kw))
        return seen
    return install


@pytest.fixture
def research(run_main, mock_orchapod_io):
    """research(**inputs) -> (corpus rows, metrics)."""
    def run(**inputs):
        outs, metrics = run_main(wr, **inputs)
        assert list(outs) == ["corpus"]
        assert mock_orchapod_io.write_output.call_args.kwargs == {"kind": "dataset"}
        return [json.loads(line) for line in Path(outs["corpus"]).read_text(encoding="utf-8").splitlines()], metrics
    return run


def results(*hits, credits=2, failed=()):
    return httpx.Response(200, json={"results": list(hits), "failed_results": list(failed), "usage": {"credits": credits}})


# --- passages and URLs --------------------------------------------------------

def test_passages_pack_paragraphs_up_to_2000_chars_and_drop_short_fragments():
    nav, p1, p2, p3, banner = "Home\nAbout us\n Contact", para("a", 300), para("b", 1800), para("c", 2500), "Accept cookies"
    text = f"{nav}\n\n{p1}\n \n{p2}\n\n\n{p3}\r\n\r\n{banner}"
    got = list(wr.passages(text))
    assert got == [f"Home About us Contact\n\n{p1}", p2, p3[:1999], f"{p3[2000:]}\n\n{banner}"]
    assert all(200 <= len(p) <= 2000 for p in got)
    assert list(wr.passages(f"{nav}\n\n{banner}")) == []                   # navigation and banners only
    assert list(wr.passages(f"{para('d', 2000)}\n\nTiny.")) == [para("d", 2000)]  # a fragment that cannot join
    assert list(wr.passages("x" * 4500)) == ["x" * 2000, "x" * 2000, "x" * 500]  # no space to cut at


@pytest.mark.parametrize("url, want", [
    ("https://example.com/a/#top", "https://example.com/a"),
    ("https://example.com/", "https://example.com"),
    (" https://example.com/a/?q=1#f ", "https://example.com/a?q=1"),
])
def test_urls_lose_fragment_and_trailing_slash(url, want):
    assert wr.norm_url(url) == want


# --- main ---------------------------------------------------------------------

def test_stub_corpus_is_deterministic_and_within_bounds(monkeypatch, research):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("TAVILY_API_KEY")
    inputs = {"queries": ["fair housing act", "respa closing disclosure"], "max_pages": 5}
    rows, m = research(**inputs)
    assert (rows, m) == research(**inputs)
    assert m == {"queries": 2, "urls": 5, "urls_failed": 0, "passages": 5, "duplicates_dropped": 0, "failed_calls": 0}
    assert all(set(r) == {"url", "text"} and 200 <= len(r["text"]) <= 2000 for r in rows)
    assert len({r["url"] for r in rows}) == 5
    assert cost.summary()["usd"] == 0


def test_each_query_is_an_advanced_search_with_raw_content(tavily, research):
    def handler(request):
        q = json.loads(request.content)["query"]
        return results(*[{"url": f"https://{q}.gov/{i}", "title": "t", "score": 0.9, "content": f"{q} snippet {i}. " * 20,
                          "raw_content": None if i == 0 else f"{q} page {i}. " * 30} for i in range(7)])
    seen = tavily(handler)
    rows, m = research(queries=["fha", "respa", "tila"], max_pages=20)
    assert seen == [("/search", {"query": q, "search_depth": "advanced", "max_results": 7, "include_raw_content": True,
                                 "include_usage": True}) for q in ("fha", "respa", "tila")]  # ⌈20 / 3⌉ results each
    assert m == {"queries": 3, "urls": 20, "urls_failed": 0, "passages": 20, "duplicates_dropped": 0, "failed_calls": 0}
    assert rows[0] == {"url": "https://fha.gov/0", "text": ("fha snippet 0. " * 20).strip()}  # no raw_content: snippet
    assert [r["url"] for r in rows][-1] == "https://tila.gov/5"  # 21 hits, capped at max_pages
    assert cost.summary() == {"usd": 0.048, "items": [{"provider": "tavily", "model": "search", "calls": 3, "in_tokens": 0,
                                                       "out_tokens": 0, "usd": 0.048, "credits": 6}]}


def test_seed_urls_are_deduped_capped_at_max_pages_and_failures_counted(tavily, research):
    page = "Escrow accounts hold funds. " * 10
    seen = tavily(lambda r: results({"url": "https://a.gov/x/", "raw_content": page + "A"},
                                    {"url": "https://b.gov/y", "raw_content": page + "B"},
                                    credits=1, failed=[{"url": "https://c.gov/z", "error": "404"}]))
    rows, m = research(seed_urls=["https://a.gov/x#top", "https://a.gov/x/", "https://b.gov/y", "https://c.gov/z",
                                  "https://d.gov/w"], max_pages=3)
    assert seen == [("/extract", {"urls": ["https://a.gov/x", "https://b.gov/y", "https://c.gov/z"],
                                  "extract_depth": "basic", "include_usage": True})]
    assert rows == [{"url": "https://a.gov/x", "text": " ".join((page + "A").split())},
                    {"url": "https://b.gov/y", "text": " ".join((page + "B").split())}]
    assert m == {"queries": 0, "urls": 2, "urls_failed": 1, "passages": 2, "duplicates_dropped": 0, "failed_calls": 0}
    assert cost.summary() == {"usd": 0.008, "items": [{"provider": "tavily", "model": "extract", "calls": 1,
                                                       "in_tokens": 0, "out_tokens": 0, "usd": 0.008, "credits": 1}]}


def test_seed_urls_come_first_and_searches_stop_once_max_pages_are_read(tavily, research):
    page = "Closing disclosure rules. " * 10
    seen = tavily(lambda r: results(*[{"url": u, "raw_content": f"{u} {page}"} for u in json.loads(r.content)["urls"]]))
    research(seed_urls=["https://a.gov/1", "https://a.gov/2"], queries=["respa"], max_pages=2)
    assert [path for path, _ in seen] == ["/extract"]  # no search credits spent once 2 pages are read


def test_exact_duplicate_passages_are_dropped(tavily, research):
    boilerplate = "Same footer on every page of this site. " * 6
    tavily(lambda r: results({"url": "https://a.gov/1", "raw_content": f"{boilerplate}\n\n{para('u', 1800)}"},
                             {"url": "https://a.gov/2", "raw_content": boilerplate}))
    rows, m = research(queries=["x"])
    assert [r["text"] for r in rows] == [boilerplate.strip(), para("u", 1800)]
    assert (m["passages"], m["duplicates_dropped"]) == (2, 1)


def test_a_lone_string_is_one_query(tavily, research):
    seen = tavily(lambda r: results({"url": "https://a.gov", "raw_content": para("a", 400)}))
    research(queries="fair housing act")
    assert [body["query"] for _, body in seen] == ["fair housing act"]


def test_server_errors_are_skipped_and_counted(tavily, research):
    answers = iter([httpx.Response(500) for _ in range(4)] + [results({"url": "https://b.gov", "raw_content": para("b", 400)})])
    tavily(lambda r: next(answers))
    rows, m = research(queries=["first", "second"])
    assert [r["url"] for r in rows] == ["https://b.gov"] and m["failed_calls"] == 1
    assert wr.log.warn.call_args.args[0].startswith("tavily server 500")


@pytest.mark.parametrize("status, kind", [(401, "auth"), (432, "quota"), (400, "bad_request")])
def test_auth_quota_and_bad_request_are_fatal(tavily, research, mock_orchapod_io, status, kind):
    tavily(lambda r: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(SystemExit) as e:
        research(queries=["q"])
    assert e.value.code == 1 and wr.log.error.call_args.args[0].startswith(f"tavily {kind} {status}: ")
    mock_orchapod_io.write_output.assert_not_called()


def test_zero_passages_is_fatal(tavily, research, mock_orchapod_io):
    tavily(lambda r: results({"url": "https://a.gov", "raw_content": "Home\n\nAbout"}))
    with pytest.raises(SystemExit) as e:
        research(queries=["q"])
    assert e.value.code == 1 and wr.log.error.call_args.args[0].startswith("0 passages")
    mock_orchapod_io.write_output.assert_not_called()


@pytest.mark.parametrize("inputs", [{}, {"queries": [], "seed_urls": [" "]}, {"queries": ["q"], "max_pages": 0},
                                    {"queries": ["q"], "max_pages": 101}])
def test_bad_inputs_are_fatal_before_any_request(tavily, research, inputs):
    seen = tavily(lambda r: results())
    with pytest.raises(SystemExit) as e:
        research(**inputs)
    assert e.value.code == 1 and seen == []


# --- image, schema and registry -----------------------------------------------

def test_image_copies_the_sdk_and_the_providers():
    docker = (ROOT / "containers/web-research/Dockerfile").read_text()
    for line in ("COPY packages/sdk-py/orchapod /app/orchapod", "COPY packages/providers /app/packages/providers",
                 "COPY containers/web-research/run.py /app/run.py"):
        assert line in docker
    assert re.search(r"pip install .*httpx", docker) and "tavily-python" not in docker


def test_schema_and_registry():
    i = WebResearchInputs(queries=["fair housing act"])
    assert (i.seed_urls, i.max_pages) == ([], 20)
    WebResearchInputs(seed_urls=["https://www.hud.gov/fair-housing"])
    for bad in ({}, {"queries": ["q"], "max_pages": 0}, {"queries": ["q"], "max_pages": 101}):
        with pytest.raises(ValidationError):
            WebResearchInputs(**bad)
    assert set(WebResearchOutputs.model_fields) == {"corpus"}
    row = NODE_REGISTRY[NodeType("web-research")]
    assert (row["inputs_schema"], row["outputs_schema"], row["runtime"]) == (WebResearchInputs, WebResearchOutputs, "cpu")
