"use client";

import { useEffect, useState } from "react";
import { TOAST_EVENT } from "@/lib/api";

/** Shows what toast() raises (failed fetches and actions): bottom right, each for 8 s or until dismissed, at most 3. */
export function Toaster() {
  const [toasts, setToasts] = useState<{ id: number; text: string }[]>([]);
  const drop = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));

  useEffect(() => {
    let next = 0;
    const show = (e: Event) => {
      const id = ++next, text = String((e as CustomEvent).detail);
      setToasts((ts) => [...ts.filter((t) => t.text !== text), { id, text }].slice(-3)); // a repeated failure shows once
      setTimeout(() => drop(id), 8000);
    };
    window.addEventListener(TOAST_EVENT, show);
    return () => window.removeEventListener(TOAST_EVENT, show);
  }, []);

  return (
    <div style={{ position: "fixed", right: 16, bottom: 16, zIndex: 1000, display: "flex", flexDirection: "column", gap: 8, width: 380, maxWidth: "calc(100vw - 32px)" }}>
      {toasts.map((t) => (
        <div key={t.id} role="alert" className="row" style={{
          gap: 8, alignItems: "flex-start", padding: "10px 12px", borderRadius: 8, fontSize: 13, lineHeight: 1.5,
          background: "var(--rose-soft)", border: "1px solid var(--rose)", color: "var(--rose-ink)", boxShadow: "var(--sh-3)",
        }}>
          <span style={{ flex: 1, minWidth: 0, wordBreak: "break-word" }}>{t.text}</span>
          <button type="button" className="btn btn-sm btn-ghost" aria-label="Dismiss" onClick={() => drop(t.id)}
            style={{ color: "inherit", padding: "0 6px" }}>×</button>
        </div>
      ))}
    </div>
  );
}
