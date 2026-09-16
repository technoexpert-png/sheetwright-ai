import type { FieldType, ResultCell, UploadStatus } from "./types";

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Confidence is 0..1 in the contract; shown as a whole percentage. */
export function formatConfidence(confidence: number): string {
  if (!Number.isFinite(confidence)) return "—";
  return `${Math.round(confidence * 100)}%`;
}

export function formatStatus(status: UploadStatus): string {
  return status === "needs_review" ? "needs review" : status;
}

export function formatFieldType(type: FieldType): string {
  return type;
}

/** Turns a stage slug like "llm_mapping" into "LLM mapping". */
export function formatStage(stage: string | null): string {
  if (!stage) return "queued";
  const words = stage.replace(/[_-]+/g, " ").trim();
  return words.replace(/\bllm\b/gi, "LLM");
}

export type CellKind = "unmapped" | "empty" | "value";

/**
 * The core product distinction, so it lives in one place: a cell with
 * `mapped: false` had NO source column to draw from (a schema gap), whereas a
 * mapped cell with a null value had a column that was blank for this row (a
 * data gap). They are different problems and must never look the same.
 */
export function cellKind(cell: ResultCell | undefined): CellKind {
  if (!cell || !cell.mapped) return "unmapped";
  if (cell.value === null || cell.value === "") return "empty";
  return "value";
}

export function cellText(cell: ResultCell): string {
  if (typeof cell.value === "boolean") return cell.value ? "true" : "false";
  return String(cell.value);
}
