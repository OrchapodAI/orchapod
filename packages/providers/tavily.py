"""Tavily client (docs/contracts.md "Provider interfaces → Tavily"): search and extract over REST, billed in credits.

    Tavily(on_usage=cost.add).extract(urls)["results"]

Retries per base.request; STUB=1 answers from a deterministic offline fake.
"""

from __future__ import annotations

import json
import math
import os

import httpx

from orchapod.prices import PRICES
from packages.providers.base import ProviderError, http_client, request, stub_hash

TAVILY_BASE = "https://api.tavily.com"
P = "tavily"


class Tavily:
    """api_key defaults to TAVILY_API_KEY; http is an httpx.Client (tests pass one on httpx.MockTransport)."""

    def __init__(self, api_key: str | None = None, *, on_usage=None, http: httpx.Client | None = None):
        self.api_key = os.environ.get("TAVILY_API_KEY") if api_key is None else api_key
        self.on_usage = on_usage
        self.stub = os.environ.get("STUB") == "1"
        self.http = http_client(_stub) if self.stub or http is None else http  # STUB never touches the network

    def search(self, query: str, *, search_depth: str = "advanced", max_results: int = 10,
               include_raw_content: bool = False, include_domains: list[str] | None = None, **params) -> dict:
        """Tavily's JSON: results[{url, title, content, score, raw_content?}]."""
        body = {"query": query, "search_depth": search_depth, "max_results": max_results,
                "include_raw_content": include_raw_content, **params}
        if include_domains:
            body["include_domains"] = include_domains
        return self._post("search", body)

    def extract(self, urls: list[str], *, extract_depth: str = "basic", **params) -> dict:
        """results[{url, raw_content}], failed_results[{url, error}]; more than 20 URLs go in batches of 20."""
        out = {"results": [], "failed_results": []}
        for i in range(0, len(urls), 20):
            data = self._post("extract", {"urls": urls[i:i + 20], "extract_depth": extract_depth, **params})
            out["results"] += data.get("results", [])
            out["failed_results"] += data.get("failed_results", [])
        return out

    def _post(self, endpoint: str, body: dict) -> dict:
        if not self.api_key and not self.stub:
            raise ProviderError(P, "auth", None, "TAVILY_API_KEY is not set")
        data = request(self.http, P, "POST", f"{TAVILY_BASE}/{endpoint}", json={**body, "include_usage": True},
                       headers={"Authorization": f"Bearer {self.api_key}"}).json()
        credits = (data.get("usage") or {}).get("credits")
        if credits is None:  # the contract's rule: 1 (basic) or 2 (advanced) per search, or per 5 extracted URLs
            per = 2 if body.get(f"{endpoint}_depth") == "advanced" else 1
            credits = per if endpoint == "search" else per * math.ceil(len(data.get("results", [])) / 5)
        if self.on_usage:
            self.on_usage(P, endpoint, credits=credits, usd=credits * PRICES["tavily"]["credit"])
        return data


_FILLER = "This deterministic stub page stands in for a real web page, so STUB=1 runs keep their shapes. " * 5


def _stub(request: httpx.Request) -> httpx.Response:
    """STUB=1: an offline Tavily with the real response shapes; every page is unique and ≥ 400 chars."""
    h, body = stub_hash(request), json.loads(request.content)

    def page(i: int) -> str:
        return f"Stub page {i} for request {h}. {_FILLER}"

    if request.url.path == "/search":
        raw = body.get("include_raw_content")
        results = [{"url": f"https://example.com/stub/{h}/{i}", "title": f"stub-{h}-{i}", "content": page(i),
                    "score": 1.0, **({"raw_content": page(i)} if raw else {})} for i in range(body["max_results"])]
        return httpx.Response(200, json={"query": body["query"], "results": results, "usage": {"credits": 0}})
    return httpx.Response(200, json={"results": [{"url": u, "raw_content": page(i)} for i, u in enumerate(body["urls"])],
                                     "failed_results": [], "usage": {"credits": 0}})
