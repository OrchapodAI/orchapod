"use client";

import clsx from "clsx";
import type { RunSummary } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { whereRuns } from "@/lib/runEvents";

interface Props {
  nodes: RunSummary["nodes"];
  activeNodeId?: string;
  onSelect: (nodeId: string) => void;
  /** Whether the run is stopped (failed or cancelled), the only time the API retries a node. */
  canRetry: boolean;
  retrying: string | null;
  onRetry: (nodeId: string) => void;
}

export function NodeTimeline({ nodes, activeNodeId, onSelect, canRetry, retrying, onRetry }: Props) {
  return (
    <div className="space-y-1">
      {nodes.map((node, i) => (
        <div key={node.node_id}>
          <button
            onClick={() => onSelect(node.node_id)}
            className={clsx(
              "w-full grid grid-cols-[1fr_auto] items-center px-3 py-2.5 rounded text-left transition-colors text-sm border",
              activeNodeId === node.node_id
                ? "bg-[#DEEBFF] border-[#0052CC] text-[#0052CC]"
                : "bg-white border-[#DFE1E6] hover:bg-[#F4F5F7] text-[#172B4D]"
            )}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="text-[11px] text-[#97A0AF] w-4 shrink-0 text-right font-medium">{i + 1}</span>
              <div className="min-w-0">
                <p className="text-xs font-semibold truncate">{node.node_id}</p>
                <p className="text-[10px] text-[#6B778C] capitalize">
                  {node.type.replace(/-/g, " ")}{node.usd > 0 && ` · $${node.usd.toFixed(3)}`}
                </p>
              </div>
            </div>
            <StatusBadge status={node.status} />
            {whereRuns(node) && <p className="col-span-2 mt-1 pl-[26px] text-[10px] text-[#6B778C] break-words">{whereRuns(node)}</p>}
          </button>
          {node.status === "failed" && (
            <div className="px-3 pt-1.5 pb-2 space-y-2">
              {node.error && (
                <p className="font-mono text-[11px] leading-snug" style={{ color: "var(--rose-ink)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {node.error}
                </p>
              )}
              <button className="btn btn-sm" disabled={!canRetry || retrying !== null} onClick={() => onRetry(node.node_id)}>
                {retrying === node.node_id ? "Retrying…" : "Retry node"}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
