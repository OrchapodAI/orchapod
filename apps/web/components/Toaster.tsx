"use client";

import { useEffect, useRef, useState } from "react";
import { TOAST_EVENT } from "@/lib/api";

const SHOW_MS = 8000;
const short = (s: string) => (s.length > 60 ? `${s.slice(0, 60)}…` : s);

/** Shows what toast() raises (failed fetches and actions): bottom right, at most 3, each until dismissed or for 8 s of time
 *  the stack is neither hovered nor focused. The one always-mounted live region announces each new toast. */
export function Toaster() {
  const [toasts, setToasts] = useState<{ id: number; text: string }[]>([]);
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const stack = useRef<HTMLDivElement>(null);
  const drop = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));

  useEffect(() => {
    let next = 0;
    const show = (e: Event) => {
      const id = ++next, text = String((e as CustomEvent).detail);
      setToasts((ts) => [...ts.filter((t) => t.text !== text), { id, text }].slice(-3)); // a repeated failure shows once
    };
    window.addEventListener(TOAST_EVENT, show);
    return () => window.removeEventListener(TOAST_EVENT, show);
  }, []);
  // a removed toast takes its focused button with it and fires no blur, so re-check focus whenever the stack changes
  useEffect(() => { if (!stack.current?.contains(document.activeElement)) setFocus(false); }, [toasts]);

  return (
    <div ref={stack} aria-live="assertive" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onFocus={() => setFocus(true)} onBlur={(e) => setFocus(e.currentTarget.contains(e.relatedTarget))}
      style={{ position: "fixed", right: 16, bottom: 16, zIndex: 1000, display: "flex", flexDirection: "column", gap: 8, width: 380, maxWidth: "calc(100vw - 32px)" }}>
      {toasts.map((t) => (
        <Toast key={t.id} text={t.text} paused={hover || focus} onDone={() => drop(t.id)} onDismiss={() => drop(t.id)} />
      ))}
    </div>
  );
}

/** One toast. Its timer counts only while unpaused: pausing keeps the time left. */
function Toast({ text, paused, onDone, onDismiss }: { text: string; paused: boolean; onDone: () => void; onDismiss: () => void }) {
  const left = useRef(SHOW_MS);
  useEffect(() => {
    if (paused) return;
    const start = Date.now(), timer = setTimeout(onDone, left.current);
    return () => { clearTimeout(timer); left.current -= Date.now() - start; };
  }, [paused]); // onDone only drops this toast's id, so the first one serves

  return (
    <div className="row" style={{
      gap: 8, alignItems: "flex-start", padding: "10px 12px", borderRadius: 8, fontSize: 13, lineHeight: 1.5,
      background: "var(--rose-soft)", border: "1px solid var(--rose)", color: "var(--rose-ink)", boxShadow: "var(--sh-3)",
    }}>
      <span style={{ flex: 1, minWidth: 0, wordBreak: "break-word" }}>{text}</span>
      <button type="button" className="btn btn-sm btn-ghost" aria-label={`Dismiss: ${short(text)}`} onClick={onDismiss}
        style={{ color: "inherit", padding: "0 6px" }}>×</button>
    </div>
  );
}
