"use client";

import clsx from "clsx";
import type { NodeRun } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

interface Props {
  nodes: NodeRun[];
  activeNodeId?: string;
  onSelect: (nodeId: string) => void;
}

export function NodeTimeline({ nodes, activeNodeId, onSelect }: Props) {
  return (
    <div className="space-y-1.5">
      {nodes.map((node, i) => (
        <button
          key={node.id}
          onClick={() => onSelect(node.node_id)}
          className={clsx(
            "w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-left transition-colors text-sm",
            activeNodeId === node.node_id
              ? "bg-violet-900/30 border border-violet-700/50"
              : "bg-slate-900 border border-slate-800 hover:border-slate-700"
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[10px] text-slate-600 w-4 shrink-0 text-right">{i + 1}</span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-slate-200 truncate">{node.node_id}</p>
              <p className="text-[10px] text-slate-600 capitalize">{node.node_type.replace("-", " ")}</p>
            </div>
          </div>
          <StatusBadge status={node.status} />
        </button>
      ))}
    </div>
  );
}
