"""Spike 2: live probes of Nemotron on Token Factory (hackathon/briefs/2026-10-22-spikes.md, "spike2").

    set -a; . /Users/hari/src/orchapod-hack/.env; set +a
    python scripts/spikes/spike2/probe.py prices|reasoning|schema|planner|report|repeat|alt|judge

Every chat call goes through packages/providers' TokenFactory.chat and appends one line to results.jsonl beside this
file: the request body as sent (headers are never read), each reply's status and body, latency and the $ billed.
A call whose worst case would take the spike past CAP is refused before it is sent. DRY=1 answers from the client's
STUB fake (no network, no key) and writes to $SPIKE2_OUT.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "apps"), str(ROOT / "packages/sdk-py")]

import httpx  # noqa: E402
import jsonschema  # noqa: E402

from orchapod.prices import PRICES  # noqa: E402
from packages.providers import tokenfactory as tfm  # noqa: E402
from packages.providers.base import ProviderError  # noqa: E402
from packages.providers.tokenfactory import LIGHTNING, SUPER, ULTRA, TokenFactory  # noqa: E402

DRY = os.environ.get("DRY") == "1"
OUT = Path(os.environ.get("SPIKE2_OUT") or Path(__file__).with_name("results.jsonl"))
CAP = 0.90  # the brief's $1, less a margin for a price-table error
OFF = {"thinking=False": {"thinking": False}, "reasoning_effort=none": {"reasoning_effort": "none"}}
SMALL = {"type": "object", "additionalProperties": False, "required": ["title", "year", "genres", "rating"],
         "properties": {"title": {"type": "string"}, "year": {"type": "integer"},
                        "genres": {"type": "array", "items": {"type": "string"}},
                        "rating": {"enum": ["G", "PG", "PG-13", "R"]}}}  # untyped enum, as planner.py and judge-eval send


def spent() -> float:
    return sum(json.loads(line).get("usd", 0) for line in OUT.read_text().splitlines()) if OUT.exists() else 0.0


def append(rec: dict) -> None:
    with OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def client(on_usage=None) -> TokenFactory:
    """A TokenFactory whose httpx client keeps each request body and reply (status, body) in tf.seen."""
    seen = []

    def on_request(r: httpx.Request):
        seen.append({"request": json.loads(r.content) if r.content else None, "status": None, "reply": None})

    def on_response(r: httpx.Response):
        r.read()
        try:
            seen[-1].update(status=r.status_code, reply=r.json())
        except ValueError:
            seen[-1].update(status=r.status_code, reply=r.text[:2000])

    http = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0),
                        transport=httpx.MockTransport(tfm._stub) if DRY else None,
                        event_hooks={"request": [on_request], "response": [on_response]})
    tf = TokenFactory("dry" if DRY else None, on_usage=on_usage, http=http)
    tf.seen = seen
    return tf


def call(label: str, messages: list[dict], model: str = SUPER, validate: dict | None = None, **kw) -> dict:
    """One TokenFactory.chat call (kw as chat takes them); validate = a JSON Schema the content must meet."""
    p = PRICES["token_factory"][model]
    worst = (len(json.dumps(messages)) * p["in"] + kw.get("max_tokens", 1024) * p["out"]) / 1e6  # ≥ 1 char a token
    if spent() + worst > CAP:
        sys.exit(f"refused {label}: ${spent():.4f} spent + ${worst:.4f} worst case > CAP ${CAP}")
    usd = []
    tf = client(lambda *a, **k: usd.append(k["usd"]))
    t0 = time.perf_counter()
    try:
        tf.chat(messages, model, **kw)
        error = None
    except ProviderError as e:
        error = str(e)
    reply = (tf.seen[-1]["reply"] if tf.seen else None) or {}
    reply = reply if isinstance(reply, dict) else {}
    choice = (reply.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    rec = {"label": label, "model": model, "latency_s": round(time.perf_counter() - t0, 2), "usd": round(sum(usd), 6),
           "statuses": [s["status"] for s in tf.seen], "error": error, "finish_reason": choice.get("finish_reason"),
           "usage": reply.get("usage"), "message_keys": sorted(msg),
           "reasoning_chars": len(msg.get("reasoning_content") or msg.get("reasoning") or ""),
           "think_tag_in_content": "</think>" in content, "content": content}
    if validate is not None:
        try:
            jsonschema.validate(json.loads(content), validate)
            rec["json"] = "valid"
        except json.JSONDecodeError as e:
            rec["json"] = f"not JSON: {e}"
        except jsonschema.ValidationError as e:
            rec["json"] = f"schema: {e.message[:300]}"
    rec["exchanges"] = tf.seen
    append(rec)
    brief = {k: v for k, v in rec.items() if k not in ("exchanges", "content")}
    print(json.dumps(brief), "| content:", content[:300].replace("\n", " "), flush=True)
    return rec


def prices():
    """Free: GET /v1/models?verbose=true, our ids only."""
    tf = client()
    data = tf._call("GET", "/models", params={"verbose": "true"})
    models = data.get("data") or []
    ours = [m for m in models if m.get("id") in (SUPER, ULTRA, LIGHTNING, tfm.NANO)]
    rec = {"label": "GET /v1/models?verbose=true", "usd": 0, "status": tf.seen[-1]["status"], "count": len(models),
           "ids": sorted(m.get("id", "") for m in models), "ours": ours}
    append(rec)
    print(json.dumps(rec, indent=1)[:6000])


def reasoning():
    """Q2: the same prompt with the default, reasoning_effort "none" and chat_template_kwargs enable_thinking false."""
    q = [{"role": "user", "content": "A train leaves at 14:35 and arrives at 17:10. How long is the trip? "
                                     "Answer in one line."}]
    for i in (1, 2):
        call(f"reasoning default #{i}", q, max_tokens=4096)
        for name, extra in OFF.items():
            call(f"reasoning {name} #{i}", q, max_tokens=4096, **extra)


def schema():
    """Q1: json_schema strict (schema only in response_format) vs json_object + the schema in the prompt."""
    ask = [{"role": "user", "content": "Describe one classic movie."}]
    told = [{"role": "user", "content": "Describe one classic movie. Answer with only a JSON object that matches this "
                                        "JSON Schema:\n" + json.dumps(SMALL)}]
    for name, extra in {"default": {}, **OFF}.items():
        call(f"schema json_schema strict, reasoning {name}", ask, validate=SMALL, json_schema=SMALL, max_tokens=4096,
             **extra)
        call(f"schema json_object + schema in prompt, reasoning {name}", told, validate=SMALL,
             response_format={"type": "json_object"}, max_tokens=4096, **extra)


def planner(**extra):
    """Q3: planner.make_plan's first call for intent #2, then its review()."""
    from api.agent import planner as p
    shape = extra or {"thinking": False}
    messages = [{"role": "system", "content": p._system_prompt()},
                {"role": "user", "content": "Create synthetic data of movie likes, shares and subscribes."}]
    rec = call(f"planner intent #2, json_schema strict, {shape}", messages, validate=p._answer_schema(),
               json_schema=p._answer_schema(), temperature=0.0, max_tokens=4096, read_timeout=300, **shape)
    try:
        answer = json.loads(rec["content"])
    except ValueError:
        answer = {}
    plan = answer.get("plan") if isinstance(answer, dict) and isinstance(answer.get("plan"), dict) else \
        {"name": "", "nodes": []}
    errors, warnings, est = p.review(plan)
    review = {"label": f"planner review() of: {rec['label']}", "usd": 0, "errors": errors, "warnings": warnings,
              "estimate": est}
    append(review)
    print(json.dumps(review))


FAKE_RUN = {  # what write_report sends: intent, plan, estimate and GET /runs/{id}/summary (fake values)
    "intent": "Create synthetic data of movie likes, shares and subscribes.",
    "estimate": {"usd": 0.15, "minutes": 6.5, "by_node": {"synth": {"usd": 0.15, "minutes": 4.5},
                                                          "prep": {"usd": 0.0, "minutes": 2}}},
    "run": {"run_id": "3f2c9a10-5b7e-4d21-9a0c-1e8f6b2d4c77", "status": "succeeded", "cost_usd": 0.0921, "error": None,
            "nodes": [{"node_id": "synth", "type": "synth-distilabel", "status": "succeeded", "usd": 0.0921,
                       "error": None, "started_at": "2026-10-22T09:00:04Z", "finished_at": "2026-10-22T09:04:41Z"},
                      {"node_id": "prep", "type": "data-prep", "status": "succeeded", "usd": 0.0, "error": None,
                       "started_at": "2026-10-22T09:04:43Z", "finished_at": "2026-10-22T09:05:30Z"}],
            "artifacts": [
                {"id": 41, "node_id": "synth", "name": "dataset", "kind": "dataset",
                 "uri": "r2://orchapod-artifacts/runs/3f2c9a10/synth/dataset",
                 "download_url": "/artifacts/41/download", "meta": {"rows": 500}},
                {"id": 42, "node_id": "prep", "name": "train_jsonl", "kind": "dataset",
                 "uri": "r2://orchapod-artifacts/runs/3f2c9a10/prep/train_jsonl",
                 "download_url": "/artifacts/42/download", "meta": {"rows": 441}},
                {"id": 43, "node_id": "prep", "name": "metrics_json", "kind": "metrics",
                 "uri": "r2://orchapod-artifacts/runs/3f2c9a10/prep/metrics_json", "download_url": None,
                 "meta": {"rows_in": 500, "rows_out": 490, "duplicates": 10, "invalid": 0,
                          "action": {"like": 0.61, "share": 0.29, "subscribe": 0.10},
                          "device": {"mobile": 0.44, "tv": 0.31, "web": 0.20, "tablet": 0.05}, "stub": False}}]}}


SCORE = {"type": "object", "properties": {"score": {"type": "integer", "enum": [1, 2, 3, 4, 5]}},
         "required": ["score"], "additionalProperties": False}  # containers/data-prep/run.py SCORE
ROW = [{"role": "user", "content": "Score this synthetic row from 1 (useless) to 5 (excellent) as training data. "
                                   "Answer with JSON {\"score\": 1-5}.\n<row>\n{\"user_id\": \"u_00042\", "
                                   "\"movie_title\": \"Casablanca\", \"action\": \"like\", \"timestamp\": "
                                   "\"2026-10-01T20:14:00Z\", \"device\": \"tv\"}\n</row>"}]


def _report_messages() -> list[dict]:
    from api.agent import planner as p
    t = next(t for t in p.templates() if t["slug"] == "movie-engagement")
    facts = json.dumps({**FAKE_RUN, "plan": t["plan"]}, default=str)[:20_000]
    return [{"role": "system", "content": p.REPORT_PROMPT}, {"role": "user", "content": facts}]


def report():
    """Q4: write_report's call on Nemotron 3.5 Lightning, plus data-prep's quality-filter shape on Lightning."""
    for name, extra in {**OFF, "default": {}}.items():
        call(f"report Lightning, reasoning {name}", _report_messages(), LIGHTNING, temperature=0.0, max_tokens=1200,
             **extra)
    for name, extra in OFF.items():
        call(f"quality-filter shape Lightning, reasoning {name}", ROW, LIGHTNING, validate=SCORE, json_schema=SCORE,
             max_tokens=64, read_timeout=30, **extra)


def repeat(part: str = "qf", n: str = "3", timeout: str = "120"):
    """Lightning latency per switch, interleaved so load drift hits both (part=qf, then report). Parts, n and the read
    timeout keep each command under 600 s."""
    for i in range(1, int(n) + 1) if part == "qf" else ():
        for name, extra in OFF.items():
            call(f"repeat quality-filter shape Lightning, reasoning {name} #{i}, read_timeout {timeout}", ROW,
                 LIGHTNING, validate=SCORE, json_schema=SCORE, max_tokens=64, read_timeout=float(timeout), **extra)
    for i in (1, 2) if part == "report" else ():
        for name, extra in OFF.items():
            call(f"repeat report Lightning, reasoning {name} #{i}", _report_messages(), LIGHTNING, temperature=0.0,
                 max_tokens=1200, **extra)


def alt():
    """Lightning was slow, so the report shape on Super and on Nano (Nano's live price from prices step, 2026-10-22,
    held in memory only: spike 1 owns prices.py). A 60 s read timeout keeps the command under 600 s."""
    PRICES["token_factory"].setdefault(tfm.NANO, {"in": 0.06, "out": 0.24})
    for model in (SUPER, tfm.NANO):
        call(f"alt report {model}, thinking=False", _report_messages(), model, temperature=0.0, max_tokens=1200,
             thinking=False, read_timeout=60)


def judge():
    """R23's open item: strict json_schema with an untyped enum on Ultra, judge-eval's shape."""
    schema = {"type": "object", "additionalProperties": False, "required": ["reasoning", "winner"],
              "properties": {"reasoning": {"type": "string"}, "winner": {"enum": ["A", "B", "tie"]}}}
    messages = [{"role": "system", "content": "You are an impartial judge. Using the reference answer as ground truth, "
                                              "decide which answer is better. Answer tie when both are equally good."},
                {"role": "user", "content": "<question>\nWhat is the capital of Australia?\n</question>\n<reference>\n"
                                            "Canberra\n</reference>\n<answer_a>\nSydney\n</answer_a>\n<answer_b>\n"
                                            "Canberra is the capital.\n</answer_b>"}]
    call("judge Ultra, json_schema strict untyped enum, thinking=False", messages, ULTRA, validate=schema,
         json_schema=schema, temperature=0.0, max_tokens=1024, thinking=False)


if __name__ == "__main__":
    step, *args = sys.argv[1:] or ["?"]
    steps = {f.__name__: f for f in (prices, reasoning, schema, planner, report, repeat, alt, judge)}
    if step not in steps:
        sys.exit(f"usage: probe.py {'|'.join(steps)}")
    steps[step](**dict(a.split("=", 1) for a in args))
    print(f"spent so far: ${spent():.4f} of CAP ${CAP}")
