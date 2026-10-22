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
  INFO:     "text-[#6B778C]",
  WARN:     "text-[#FF8B00]",
  ERROR:    "text-[#DE350B]",
  PROGRESS: "text-[#6554C0]",
};

interface Props {
  lines: LogLine[];
  activeNodeId?: string;
  connected: boolean;
}

export function LogStream({ lines, activeNodeId, connected }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {  // scroll the log box only: scrollIntoView also moved the page, pulling a reader back on every line
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [lines.length]);

  const filtered = activeNodeId
    ? lines.filter((l) => l.node_id === activeNodeId)
    : lines;

  return (
    <div className="flex flex-col h-full bg-white rounded border border-[#DFE1E6] overflow-hidden shadow-sm">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#DFE1E6] bg-[#F4F5F7] shrink-0">
        <p className="text-xs font-semibold text-[#172B4D] uppercase tracking-wide">Logs</p>
        <div className="flex items-center gap-1.5">
          <div className={clsx(
            "w-1.5 h-1.5 rounded-full",
            connected ? "bg-[#00875A] animate-pulse" : "bg-[#C1C7D0]"
          )} />
          <span className="text-[11px] text-[#6B778C]">{connected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      <div ref={boxRef} className="flex-1 overflow-y-auto p-4 space-y-0.5 font-mono text-xs bg-[#FAFBFC]">
        {filtered.length === 0 ? (
          <p className="text-[#97A0AF] italic">Waiting for logs…</p>
        ) : (
          filtered.map((line, i) => (
            <div key={i} className="flex gap-3 hover:bg-[#F4F5F7] px-1 py-0.5 rounded log-line">
              <span className="text-[#97A0AF] shrink-0 w-20 truncate">
                {new Date(line.ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className={clsx("shrink-0 w-16", LEVEL_COLOR[line.level] ?? "text-[#6B778C]")}>
                [{line.level}]
              </span>
              <span className="text-[#172B4D] break-all">{line.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
