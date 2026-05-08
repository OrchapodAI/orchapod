import type { RunStatus, NodeStatus } from "@/lib/types";

type Status = RunStatus | NodeStatus;

const PILL_CLASS: Record<Status, string> = {
  pending:          "pending",
  provisioning_gpu: "provisioning",
  running:          "running",
  succeeded:        "succeeded",
  failed:           "failed",
  cancelled:        "cancelled",
};

const LABELS: Record<Status, string> = {
  pending:          "Pending",
  provisioning_gpu: "Provisioning",
  running:          "Running",
  succeeded:        "Done",
  failed:           "Failed",
  cancelled:        "Cancelled",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`pill ${PILL_CLASS[status]}`}>
      <span className="dot" />
      {LABELS[status]}
    </span>
  );
}
