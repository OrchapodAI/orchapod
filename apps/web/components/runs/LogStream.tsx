"use client";

import { useEffect, useRef } from "react";
import clsx from "clsx";

export interface LogLine {
  ts: string;
  level: string;
  node_id: string;
  message: string;
}

const LEVEL_COLOR: Record<string, string> = {
  INFO:     "text-slate-400",
  WARN:     "text-amber-400",
  ERROR:    "text-red-400",
  PROGRESS: "text-violet-400",
};

interface Props {
  lines: LogLine[];
  activeNodeId?: string;
  connected: boolean;
}

export function LogStream({ lines, activeNodeId, connected }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  const filtered = activeNodeId
    ? lines.filter((l) => l.node_id === activeNodeId)
    : lines;

  return (
    <div className="flex flex-col h-full bg-slate-950 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 shrink-0">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Logs</p>
        <div className="flex items-center gap-1.5">
          <div className={clsx("w-1.5 h-1.5 rounded-full", connected ? "bg-emerald-400 animate-pulse" : "bg-slate-600")} />
          <span className="text-[10px] text-slate-500">{connected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      {/* Log lines */}
      <div className="flex-1 overflow-y-auto p-4 space-y-0.5 font-mono text-xs">
        {filtered.length === 0 ? (
          <p className="text-slate-700 italic">Waiting for logs…</p>
        ) : (
          filtered.map((line, i) => (
            <div key={i} className="flex gap-3 hover:bg-slate-900/50 px-1 py-0.5 rounded log-line">
              <span className="text-slate-700 shrink-0 w-20 truncate">
                {new Date(line.ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className={clsx("shrink-0 w-16", LEVEL_COLOR[line.level] ?? "text-slate-500")}>
                [{line.level}]
              </span>
              <span className="text-slate-300 break-all">{line.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
