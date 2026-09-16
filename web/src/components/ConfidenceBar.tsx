import { formatConfidence } from "../lib/format";

interface Props {
  confidence: number;
  /** Rendered smaller inside alternative chips. */
  compact?: boolean;
}

/**
 * Confidence is the one place besides primary actions where the accent is
 * allowed, because it is the number the user is really being asked to judge.
 * Below 0.75 the fill shifts to the muted warning/error tones so a weak guess
 * is legible at a glance without reading the figure.
 */
function tone(confidence: number): string {
  if (confidence >= 0.75) return "bg-accent";
  if (confidence >= 0.5) return "bg-warning";
  return "bg-error";
}

export function ConfidenceBar({ confidence, compact = false }: Props) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(confidence) ? confidence : 0));
  const label = formatConfidence(confidence);

  return (
    <span className="flex items-center gap-2">
      <span
        role="meter"
        aria-label="Mapping confidence"
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={label}
        className={`block ${compact ? "h-1 w-10" : "h-1.5 w-20"} overflow-hidden rounded-md bg-line`}
      >
        <span
          className={`block h-full rounded-md ${tone(clamped)}`}
          style={{ width: `${clamped * 100}%` }}
        />
      </span>
      <span className={`data ${compact ? "text-[0.6875rem]" : ""} text-ink`}>{label}</span>
    </span>
  );
}
