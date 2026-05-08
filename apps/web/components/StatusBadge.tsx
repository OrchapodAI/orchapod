import clsx from "clsx";
import type { RunStatus, NodeStatus } from "@/lib/types";

type Status = RunStatus | NodeStatus;

const STYLES: Record<Status, string> = {
  pending:          "bg-slate-800 text-slate-400",
  provisioning_gpu: "bg-amber-900/40 text-amber-400 animate-pulse",
  running:          "bg-blue-900/40 text-blue-400 animate-pulse",
  succeeded:        "bg-emerald-900/40 text-emerald-400",
  failed:           "bg-red-900/40 text-red-400",
  cancelled:        "bg-slate-800 text-slate-500",
};

const LABELS: Record<Status, string> = {
  pending:          "Pending",
  provisioning_gpu: "Provisioning GPU",
  running:          "Running",
  succeeded:        "Succeeded",
  failed:           "Failed",
  cancelled:        "Cancelled",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={clsx("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium", STYLES[status])}>
      {LABELS[status]}
    </span>
  );
}
