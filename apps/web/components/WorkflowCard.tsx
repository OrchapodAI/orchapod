"use client";

import Link from "next/link";
import { GitBranch, Clock, ChevronRight, Trash2 } from "lucide-react";
import type { Workflow } from "@/lib/types";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

interface Props {
  workflow: Workflow;
  onDelete: () => void;
}

export function WorkflowCard({ workflow, onDelete }: Props) {
  const nodeCount = workflow.graph_json?.nodes?.length ?? 0;
  const date = new Date(workflow.updated_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete "${workflow.name}"? This cannot be undone.`)) return;
    await api.workflows.delete(workflow.id);
    onDelete();
  }

  return (
    <Link
      href={`/canvas/${workflow.id}`}
      className="group block bg-white border border-[#DFE1E6] rounded p-4 hover:border-[#0052CC] hover:shadow-md transition-all shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-[#172B4D] truncate group-hover:text-[#0052CC] transition-colors text-sm">
            {workflow.name}
          </h3>
          <p className="text-xs text-[#6B778C] mt-0.5">v{workflow.version}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleDelete}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded text-[#97A0AF] hover:text-[#BF2600] hover:bg-[#FFEBE6] transition-all"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <ChevronRight className="w-4 h-4 text-[#97A0AF] group-hover:text-[#0052CC] transition-colors" />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-[#6B778C]">
        <span className="flex items-center gap-1.5">
          <GitBranch className="w-3.5 h-3.5" />
          {nodeCount} {nodeCount === 1 ? "node" : "nodes"}
        </span>
        <span className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          {date}
        </span>
      </div>
    </Link>
  );
}
