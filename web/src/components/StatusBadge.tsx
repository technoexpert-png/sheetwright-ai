import type { UploadStatus } from "../lib/types";
import { formatStatus } from "../lib/format";

// Muted semantics: only `needs_review` earns the accent, because it is the one
// status that demands the user do something.
const TONE: Record<UploadStatus, string> = {
  pending: "border-line-strong bg-paper text-info",
  running: "border-line-strong bg-paper text-info",
  needs_review: "border-accent/40 bg-accent-wash text-accent-strong",
  complete: "border-line-strong bg-white text-ink",
  error: "border-error/30 bg-error-wash text-error",
};

export function StatusBadge({ status }: { status: UploadStatus }) {
  return (
    <span
      className={`data inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs ${TONE[status]}`}
    >
      {formatStatus(status)}
    </span>
  );
}
