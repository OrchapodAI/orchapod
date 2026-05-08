"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Search, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { Workflow } from "@/lib/types";
import { WorkflowCard } from "@/components/WorkflowCard";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await api.workflows.list();
      setWorkflows(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const filtered = workflows.filter((w) =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-8 py-6 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Workflows</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {workflows.length} workflow{workflows.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/workflows/new"
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            New workflow
          </Link>
        </div>
      </div>

      {/* Search */}
      <div className="px-8 pt-5">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search workflows…"
            className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-4 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-violet-600 transition-colors"
          />
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 px-8 py-5 overflow-auto">
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-28 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState hasSearch={search.length > 0} />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((w) => (
              <WorkflowCard key={w.id} workflow={w} onDelete={load} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ hasSearch }: { hasSearch: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-12 h-12 rounded-2xl bg-violet-900/30 flex items-center justify-center mb-4">
        <Sparkles className="w-6 h-6 text-violet-400" />
      </div>
      <h3 className="text-slate-300 font-medium">
        {hasSearch ? "No workflows match your search" : "No workflows yet"}
      </h3>
      <p className="text-slate-500 text-sm mt-1.5 max-w-xs">
        {hasSearch
          ? "Try a different search term."
          : "Create your first workflow by describing your fine-tuning goal or uploading a YAML definition."}
      </p>
      {!hasSearch && (
        <Link
          href="/workflows/new"
          className="mt-5 flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New workflow
        </Link>
      )}
    </div>
  );
}
