# Spike 3 report — Tavily extract + search (orchestrator, 2026-10-24) · spend: 6 Tavily credits (≈ $0.048)

Script: the session scratchpad's spike3.py (counts only; never page content or the key), against packages/providers/tavily.py
and containers/web-research/run.py's `passages()` chunker, on template 4's own 20 seed URLs (the golden path's research step).

- **extract** (basic): 20 URLs → **20 ok, 0 failed** in 0.2 s; result keys `images, raw_content, title, url` (the client's
  `results[{url, raw_content}]` shape holds; `images` is extra and unused). 178,894 chars in all, 410–36,537 per page.
- **chunker**: **98 passages**, every page ≥ 1 (min 1, max 21: serverless/endpoints/manage). Template 4's grounded synth
  draws its Q&A from these.
- **search** (advanced, include_domains docs.tokenfactory.nebius.com + docs.nebius.com, max_results 10): 10 results in 5.7 s;
  keys `content, id, raw_content, score, title, url` (`id` is new, unused); all 10 from docs.tokenfactory for this query.
- **credits**: extract 4 (1 per 5 URLs, basic) + search 2 (advanced) = 6, matching the contract's rule and PRICES ($0.008/credit).
- Verdict: the Tavily path of the golden run works as built; nothing to change.
