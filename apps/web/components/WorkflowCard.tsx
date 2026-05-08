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
  const router = useRouter();
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
      className="group block bg-slate-900 border border-slate-800 rounded-xl p-5 hover:border-violet-600/50 hover:bg-slate-800/60 transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-100 truncate group-hover:text-violet-300 transition-colors">
            {workflow.name}
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">v{workflow.version}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleDelete}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded-md text-slate-500 hover:text-red-400 hover:bg-red-900/20 transition-all"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-violet-400 transition-colors" />
        </div>
      </div>

      <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
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
