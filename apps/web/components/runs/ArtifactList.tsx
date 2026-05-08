"use client";

import { Database, Box, BarChart2, FileText, Globe, Download } from "lucide-react";
import type { Artifact } from "@/lib/types";

const KIND_ICON: Record<string, React.ElementType> = {
  dataset:  Database,
  model:    Box,
  metrics:  BarChart2,
  log:      FileText,
  endpoint: Globe,
};

const KIND_COLOR: Record<string, string> = {
  dataset:  "text-sky-400 bg-sky-950/40",
  model:    "text-violet-400 bg-violet-950/40",
  metrics:  "text-emerald-400 bg-emerald-950/40",
  log:      "text-slate-400 bg-slate-800",
  endpoint: "text-rose-400 bg-rose-950/40",
};

function formatBytes(bytes: number | null) {
  if (!bytes) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

interface Props {
  artifacts: Artifact[];
}

export function ArtifactList({ artifacts }: Props) {
  if (artifacts.length === 0) {
    return (
      <p className="text-sm text-slate-700 italic py-4">
        Artifacts will appear here as nodes complete.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {artifacts.map((art) => {
        const Icon = KIND_ICON[art.kind] ?? FileText;
        const color = KIND_COLOR[art.kind] ?? "text-slate-400 bg-slate-800";
        const size = formatBytes(art.size_bytes);

        return (
          <div
            key={art.id}
            className="flex items-center justify-between gap-3 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2.5"
          >
            <div className="flex items-center gap-3 min-w-0">
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
                <Icon className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-200 truncate">{art.name}</p>
                <p className="text-[10px] text-slate-600 truncate font-mono">{art.uri}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {size && <span className="text-[10px] text-slate-500">{size}</span>}
              <button className="p-1.5 rounded-md text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors">
                <Download className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
