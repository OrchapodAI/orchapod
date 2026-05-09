"use client";

import { Database, Box, BarChart2, FileText, Globe, Download } from "lucide-react";
import type { Artifact } from "@/lib/types";

const KIND_META: Record<string, { icon: React.ElementType; accent: string; bg: string }> = {
  dataset:  { icon: Database,  accent: "#0065FF", bg: "#DEEBFF" },
  model:    { icon: Box,       accent: "#6554C0", bg: "#EAE6FF" },
  metrics:  { icon: BarChart2, accent: "#00875A", bg: "#E3FCEF" },
  log:      { icon: FileText,  accent: "#6B778C", bg: "#EBECF0" },
  endpoint: { icon: Globe,     accent: "#DE350B", bg: "#FFEBE6" },
};

function formatBytes(bytes: number | null) {
  if (!bytes) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function ArtifactList({ artifacts }: { artifacts: Artifact[] }) {
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
        const size = formatBytes(art.size_bytes);

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
              {size && <span className="text-[11px] text-[#6B778C]">{size}</span>}
              <a
                href={art.uri}
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
