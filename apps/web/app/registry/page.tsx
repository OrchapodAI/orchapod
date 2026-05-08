"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Cpu, BookOpen } from "lucide-react";
import { api } from "@/lib/api";
import type { BaseModel, PublicDataset } from "@/lib/types";
import clsx from "clsx";

type Tab = "models" | "datasets";

export default function RegistryPage() {
  const [tab, setTab] = useState<Tab>("models");
  const [models, setModels] = useState<BaseModel[]>([]);
  const [datasets, setDatasets] = useState<PublicDataset[]>([]);

  useEffect(() => {
    api.registry.models().then((r) => setModels(r.models));
    api.registry.datasets().then((r) => setDatasets(r.datasets));
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="px-8 py-6 border-b border-slate-800">
        <h1 className="text-xl font-semibold text-slate-100">Registry</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Curated base models and public datasets ready to use.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-8 pt-4">
        {(["models", "datasets"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              "px-5 py-2 text-sm font-medium rounded-lg transition-colors capitalize",
              tab === t
                ? "bg-violet-600/20 text-violet-300"
                : "text-slate-500 hover:text-slate-300"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-8 py-4">
        {tab === "models" && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {models.map((m) => (
              <div key={m.id} className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">{m.name}</h3>
                    <p className="text-xs text-slate-500 mt-0.5">{m.family}</p>
                  </div>
                  <a
                    href={m.hf_url}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1.5 text-slate-600 hover:text-slate-300 transition-colors"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-slate-950 rounded-lg p-2.5">
                    <p className="text-slate-600">Params</p>
                    <p className="text-slate-200 font-medium mt-0.5">{m.params_b}B</p>
                  </div>
                  <div className="bg-slate-950 rounded-lg p-2.5">
                    <p className="text-slate-600">Context</p>
                    <p className="text-slate-200 font-medium mt-0.5">{(m.context_len / 1000).toFixed(0)}K</p>
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-1.5">
                  <Cpu className="w-3 h-3 text-slate-600" />
                  <span className="text-[10px] text-slate-500">{m.recommended_gpu}</span>
                  {m.requires_hf_token && (
                    <span className="ml-auto text-[10px] text-amber-400 bg-amber-900/30 px-1.5 py-0.5 rounded-full">
                      HF token required
                    </span>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap gap-1">
                  {m.use_cases.map((uc) => (
                    <span key={uc} className="text-[10px] bg-slate-800 text-slate-500 px-2 py-0.5 rounded-full">
                      {uc}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "datasets" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {datasets.map((ds) => (
              <div key={ds.id} className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">{ds.name}</h3>
                    <p className="text-xs text-slate-500 mt-1 leading-relaxed">{ds.description}</p>
                  </div>
                  <a
                    href={ds.hf_url}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1.5 text-slate-600 hover:text-slate-300 transition-colors shrink-0"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>

                <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <BookOpen className="w-3.5 h-3.5" />
                    {ds.size}
                  </span>
                  <span className="bg-slate-800 px-2 py-0.5 rounded-full font-mono">{ds.format}</span>
                </div>

                <div className="mt-3 flex flex-wrap gap-1">
                  {ds.use_cases.map((uc) => (
                    <span key={uc} className="text-[10px] bg-slate-800 text-slate-500 px-2 py-0.5 rounded-full">
                      {uc}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
