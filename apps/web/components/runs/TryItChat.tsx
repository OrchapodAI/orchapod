"use client";

/**
 * TryItChat — KAN-29
 *
 * Live chat box that streams tokens directly from the vLLM
 * OpenAI-compatible endpoint. No API proxy — the browser calls
 * the endpoint URL directly.
 *
 * Props:
 *   endpointUrl  — base URL, e.g. https://abc.trycloudflare.com/v1
 *   apiKey       — optional bearer token (vLLM accepts anything by default)
 *   model        — model name used in /v1/chat/completions
 */

import { useEffect, useRef, useState } from "react";

interface Message {
  role: "system" | "user" | "assistant";
  content: string;
}

interface Stats {
  latencyMs:   number | null;   // time-to-first-token
  tokensPerSec: number | null;
  totalTokens:  number;
  durationMs:  number | null;
}

interface Props {
  endpointUrl: string;
  apiKey:      string | null;
  model:       string;
  /** Accumulated run cost in USD — kept live by the run viewer via run_cost WS events. */
  costUsd:     number | null;
}

const DEFAULT_SYSTEM = "You are a helpful assistant.";

export function TryItChat({ endpointUrl, apiKey, model, costUsd }: Props) {
  const [messages,    setMessages]    = useState<Message[]>([]);
  const [input,       setInput]       = useState("");
  const [streaming,   setStreaming]   = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [stats,       setStats]       = useState<Stats>({ latencyMs: null, tokensPerSec: null, totalTokens: 0, durationMs: null });
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM);
  const [showSystem,  setShowSystem]  = useState(false);

  const abortRef  = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setError(null);

    const userMsg: Message = { role: "user", content: text };
    const history: Message[] = [...messages, userMsg];
    setMessages(history);

    // Placeholder assistant message — we'll stream into it
    setMessages([...history, { role: "assistant", content: "" }]);

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);

    const startMs  = Date.now();
    let firstToken = true;
    let latencyMs: number | null  = null;
    let tokenCount = 0;

    try {
      const baseUrl = endpointUrl.replace(/\/+$/, "");
      const res = await fetch(`${baseUrl}/chat/completions`, {
        method:  "POST",
        headers: {
          "Content-Type":  "application/json",
          "Authorization": `Bearer ${apiKey ?? "orchapod"}`,
        },
        body: JSON.stringify({
          model,
          stream: true,
          messages: [
            { role: "system", content: systemPrompt },
            ...history,
          ],
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body}`);
      }

      if (!res.body) throw new Error("No response body");

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buf     = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });

        // Process all complete SSE lines
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";   // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") break;

          try {
            const chunk = JSON.parse(data);
            const delta = chunk.choices?.[0]?.delta?.content;
            if (delta == null) continue;

            if (firstToken) {
              latencyMs  = Date.now() - startMs;
              firstToken = false;
            }
            tokenCount++;

            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "assistant") {
                next[next.length - 1] = { ...last, content: last.content + delta };
              }
              return next;
            });
          } catch {
            // malformed SSE line — skip
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // user cancelled — leave partial message as-is
      } else {
        const msg = err instanceof Error ? err.message : "Request failed";
        const isTimeout = msg.includes("504") || msg.includes("ETIMEDOUT") || msg.includes("fetch");
        setError(isTimeout
          ? "Endpoint timed out. The pod may have shut down — check the countdown above."
          : `Error: ${msg}`
        );
        // Remove the empty placeholder if nothing was streamed
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          return last?.role === "assistant" && !last.content ? prev.slice(0, -1) : prev;
        });
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);

      const durationMs = Date.now() - startMs;
      setStats({
        latencyMs,
        tokensPerSec: durationMs > 0 ? Math.round((tokenCount / durationMs) * 1000) : null,
        totalTokens:  tokenCount,
        durationMs,
      });
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  function clearChat() {
    setMessages([]);
    setError(null);
    setStats({ latencyMs: null, tokensPerSec: null, totalTokens: 0, durationMs: null });
  }

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 420 }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px",
        borderBottom: "1px solid var(--line)",
        background: "var(--bg-2)",
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexShrink: 0,
      }}>
        <span className="muted mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", flex: 1 }}>
          Try it
        </span>

        {/* Stats */}
        <span className="muted" style={{ fontSize: 11.5, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {stats.latencyMs != null && (
            <>
              <span>TTFT {stats.latencyMs}ms</span>
              {stats.tokensPerSec != null && <span>· {stats.tokensPerSec} tok/s</span>}
              <span>· {stats.totalTokens} tokens</span>
            </>
          )}
          {costUsd != null && (
            <span style={{ color: "var(--ink-2)", fontWeight: 500 }}>
              {stats.latencyMs != null && "· "}
              ${costUsd.toFixed(4)} total
            </span>
          )}
        </span>

        <button
          onClick={() => setShowSystem((v) => !v)}
          className="btn btn-sm"
          title="Configure system prompt"
        >
          {showSystem ? "Hide system prompt" : "System prompt"}
        </button>
        <button onClick={clearChat} className="btn btn-sm" disabled={streaming || messages.length === 0}>
          Clear
        </button>
      </div>

      {/* System prompt editor */}
      {showSystem && (
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)", background: "var(--surface)", flexShrink: 0 }}>
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={3}
            style={{
              width: "100%",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              background: "var(--bg-2)",
              border: "1px solid var(--line)",
              borderRadius: 4,
              padding: "6px 8px",
              color: "var(--ink-1)",
              resize: "vertical",
              boxSizing: "border-box",
            }}
            placeholder="System prompt…"
          />
        </div>
      )}

      {/* Message list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.length === 0 && (
          <p className="muted" style={{ fontSize: 12.5, fontStyle: "italic", margin: "auto", textAlign: "center" }}>
            Send a message to test the live endpoint.
          </p>
        )}
        {messages.filter((m) => m.role !== "system").map((msg, i) => (
          <div
            key={i}
            style={{
              display:       "flex",
              flexDirection: msg.role === "user" ? "row-reverse" : "row",
              gap:           8,
              alignItems:    "flex-start",
            }}
          >
            <span style={{
              fontSize:    10,
              fontWeight:  600,
              color:       msg.role === "user" ? "var(--brand-ink)" : "var(--ink-3)",
              marginTop:   4,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              flexShrink:  0,
            }}>
              {msg.role === "user" ? "You" : "AI"}
            </span>
            <div style={{
              maxWidth:     "78%",
              background:   msg.role === "user" ? "var(--brand-soft)" : "var(--bg-2)",
              border:       "1px solid var(--line)",
              borderRadius: 8,
              padding:      "8px 12px",
              fontSize:     13,
              lineHeight:   1.6,
              color:        "var(--ink-1)",
              whiteSpace:   "pre-wrap",
              wordBreak:    "break-word",
            }}>
              {msg.content}
              {/* Blinking cursor while this message is streaming */}
              {streaming && msg.role === "assistant" && i === messages.length - 1 && (
                <span style={{ animation: "blink 1s step-end infinite", opacity: 0.7 }}>▌</span>
              )}
            </div>
          </div>
        ))}

        {error && (
          <div style={{
            background: "var(--rose-soft)",
            border:     "1px solid var(--rose)",
            borderRadius: 6,
            padding:    "8px 12px",
            fontSize:   12.5,
            color:      "var(--rose-ink)",
          }}>
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{
        padding:      "10px 14px",
        borderTop:    "1px solid var(--line)",
        display:      "flex",
        gap:          8,
        flexShrink:   0,
        background:   "var(--surface)",
      }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
          disabled={streaming}
          placeholder="Message… (Enter to send, Shift+Enter for newline)"
          rows={2}
          style={{
            flex:        1,
            fontFamily:  "var(--font-ui)",
            fontSize:    13,
            background:  "var(--bg-2)",
            border:      "1px solid var(--line)",
            borderRadius: 6,
            padding:     "7px 10px",
            color:       "var(--ink-1)",
            resize:      "none",
            outline:     "none",
          }}
        />
        {streaming ? (
          <button onClick={stopStreaming} className="btn btn-sm" style={{ alignSelf: "flex-end", color: "var(--rose-ink)", background: "var(--rose-soft)", borderColor: "var(--rose)" }}>
            Stop
          </button>
        ) : (
          <button onClick={sendMessage} className="btn btn-sm" disabled={!input.trim()} style={{ alignSelf: "flex-end" }}>
            Send
          </button>
        )}
      </div>

      {/* Blinking cursor keyframe */}
      <style>{`@keyframes blink { 50% { opacity: 0; } }`}</style>
    </div>
  );
}
