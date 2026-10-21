"use client";

import { Database, Box, BarChart2, FileText, Globe, Download } from "lucide-react";
import { BASE } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

const KIND_META: Record<string, { icon: React.ElementType; accent: string; bg: string }> = {
  dataset:  { icon: Database,  accent: "#0065FF", bg: "#DEEBFF" },
  model:    { icon: Box,       accent: "#6554C0", bg: "#EAE6FF" },
  metrics:  { icon: BarChart2, accent: "#00875A", bg: "#E3FCEF" },
  log:      { icon: FileText,  accent: "#6B778C", bg: "#EBECF0" },
  endpoint: { icon: Globe,     accent: "#DE350B", bg: "#FFEBE6" },
};

export function ArtifactList({ artifacts }: { artifacts: RunSummary["artifacts"] }) {
  if (artifacts.length === 0) {
    return (
      <p className="text-sm text-[#97A0AF] italic py-4">
        Artifacts will appear here as nodes complete.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {artifacts.map((art) => {
        const meta = KIND_META[art.kind] ?? KIND_META["log"];
        const Icon = meta.icon;

        return (
          <div
            key={art.id}
            className="flex items-center justify-between gap-3 bg-white border border-[#DFE1E6] rounded px-3 py-2.5 hover:shadow-sm transition-shadow"
          >
            <div className="flex items-center gap-3 min-w-0">
              <div
                className="w-7 h-7 rounded flex items-center justify-center shrink-0"
                style={{ backgroundColor: meta.bg }}
              >
                <Icon className="w-4 h-4" style={{ color: meta.accent }} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#172B4D] truncate">{art.name}</p>
                <p className="text-[10px] text-[#97A0AF] truncate font-mono">{art.uri}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <a
                href={art.download_url ? `${BASE}${art.download_url}` : art.uri}
                target="_blank"
                rel="noreferrer"
                download
                className="p-1.5 rounded text-[#6B778C] hover:text-[#0052CC] hover:bg-[#DEEBFF] transition-colors"
                title={`Download ${art.name}`}
              >
                <Download className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        );
      })}
    </div>
  );
}
