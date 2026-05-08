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
    <div className="space-y-1">
      {nodes.map((node, i) => (
        <button
          key={node.id}
          onClick={() => onSelect(node.node_id)}
          className={clsx(
            "w-full flex items-center justify-between px-3 py-2.5 rounded text-left transition-colors text-sm border",
            activeNodeId === node.node_id
              ? "bg-[#DEEBFF] border-[#0052CC] text-[#0052CC]"
              : "bg-white border-[#DFE1E6] hover:bg-[#F4F5F7] text-[#172B4D]"
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[11px] text-[#97A0AF] w-4 shrink-0 text-right font-medium">{i + 1}</span>
            <div className="min-w-0">
              <p className="text-xs font-semibold truncate">{node.node_id}</p>
              <p className="text-[10px] text-[#6B778C] capitalize">{node.node_type.replace(/-/g, " ")}</p>
            </div>
          </div>
          <StatusBadge status={node.status} />
        </button>
      ))}
    </div>
  );
}
