"""
containers/web-research/run.py — node web-research (cpu). Contract: docs/contracts.md "Data nodes → web-research".

Tavily, through packages.providers: extract for the seed URLs, then an advanced search with raw page content per
query, until max_pages pages are read → `corpus`, one {"url", "text"} per passage of 200–2,000 chars cut at
paragraph breaks, URLs normalised (no fragment, no trailing slash) and deduped, exact-duplicate passages dropped.
Credits are billed through cost.add. STUB=1 runs the same path on the client's offline stub.
"""

import json
import math
import re
import sys
from urllib.parse import urlsplit, urlunsplit

from orchapod import cost, io, log
from packages.providers.base import ProviderError
from packages.providers.tavily import Tavily

MIN_CHARS, MAX_CHARS = 200, 2000
MIN_PARAGRAPH = 40  # shorter paragraphs are navigation and banner fragments: dropped before packing


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def strings(value) -> list[str]:
    """A list input as non-empty stripped strings; a lone string is a one-item list."""
    values = [value] if isinstance(value, str) else value or []
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def norm_url(url: str) -> str | None:
    """Lower-case host, no fragment, no trailing slash, no lone surrogates; None for a malformed URL."""
    try:
        parts = urlsplit(url.strip().encode("utf-8", "ignore").decode())
    except ValueError:
        return None
    return urlunsplit(parts._replace(netloc=parts.netloc.lower(), path=parts.path.rstrip("/"), fragment=""))


def paragraphs(text: str):
    """Whitespace-collapsed paragraphs of at least MIN_PARAGRAPH chars; one over MAX_CHARS is cut at its last space
    before the limit."""
    for p in re.split(r"\n\s*\n", text):
        p = " ".join(p.split())
        if len(p) < MIN_PARAGRAPH:
            continue
        while len(p) > MAX_CHARS:
            cut = p.rfind(" ", 1, MAX_CHARS + 1)
            cut = cut if cut > 0 else MAX_CHARS
            yield p[:cut]
            p = p[cut:].lstrip()
        if p:
            yield p


def passages(text: str):
    """Consecutive paragraphs packed up to MAX_CHARS; a passage under MIN_CHARS (navigation, banners) is dropped."""
    buf = ""
    for p in paragraphs(text):
        if buf and len(buf) + 2 + len(p) > MAX_CHARS:
            if len(buf) >= MIN_CHARS:
                yield buf
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if len(buf) >= MIN_CHARS:
        yield buf


def main():
    inputs = io.read_inputs()
    queries, seeds = strings(inputs.get("queries")), [norm_url(u) for u in strings(inputs.get("seed_urls"))]
    seed_urls = list(dict.fromkeys(u for u in seeds if u))
    max_pages = 20 if inputs.get("max_pages") in (None, "") else int(inputs["max_pages"])
    if not queries and not seeds:
        fail("web-research needs at least one of queries and seed_urls")
    if not 1 <= max_pages <= 100:
        fail(f"max_pages must be 1–100, got {max_pages}")

    tavily = Tavily(on_usage=cost.add)
    per_query = min(20, math.ceil(max_pages / len(queries))) if queries else 0  # Tavily returns at most 20 results
    calls = ([("extract", seed_urls[:max_pages])] if seed_urls else []) + [("search", q) for q in queries]
    pages, urls_failed, failed_calls = {}, seeds.count(None), 0
    for i, (kind, arg) in enumerate(calls, 1):
        if len(pages) >= max_pages:
            break  # no credits for results that would not be read
        try:
            if kind == "extract":
                reply = tavily.extract(arg)
                urls_failed += len(reply["failed_results"])
            else:
                reply = tavily.search(arg, search_depth="advanced", include_raw_content=True, max_results=per_query)
        except ProviderError as e:
            if e.kind in ("auth", "bad_request", "quota"):
                fail(str(e))
            failed_calls += 1
            log.warn(str(e))
            continue
        for hit in reply.get("results") or []:
            url = norm_url(hit.get("url") or "")
            if url is None:
                urls_failed += 1
            elif url and url not in pages and len(pages) < max_pages:  # lone surrogates go once, here
                pages[url] = (hit.get("raw_content") or hit.get("content") or "").encode("utf-8", "ignore").decode()
        log.progress(i, len(calls))

    corpus, seen, duplicates = [], set(), 0
    for url, page in pages.items():
        for text in passages(page):
            if text in seen:
                duplicates += 1
            else:
                seen.add(text)
                corpus.append({"url": url, "text": text})
    metrics = {"queries": len(queries), "urls": len(pages), "urls_failed": urls_failed, "passages": len(corpus),
               "duplicates_dropped": duplicates, "failed_calls": failed_calls}
    if not corpus:
        fail(f"0 passages: {json.dumps(metrics)}")

    path = io.local_path("corpus")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in corpus)
    io.write_output("corpus", path, kind="dataset")
    io.write_metrics(metrics)
    log.info(f"web-research: {len(corpus)} passages from {len(pages)} pages, ${cost.total():.4f}")


if __name__ == "__main__":
    main()
