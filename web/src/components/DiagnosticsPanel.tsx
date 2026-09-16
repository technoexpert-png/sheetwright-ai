import { useMemo } from "react";
import type { Diagnostic, Severity } from "../lib/types";
import { EmptyState } from "./StateBlocks";

interface Props {
  diagnostics: Diagnostic[];
  /** Scrolls the preview to a source row. */
  onFocusRow: (sourceRow: number) => void;
}

// Most severe first: the list is a work queue, not a log.
const ORDER: Severity[] = ["error", "warning", "info"];

const TONE: Record<Severity, { label: string; chip: string; rule: string }> = {
  error: { label: "Errors", chip: "border-error/40 text-error", rule: "border-l-error" },
  warning: {
    label: "Warnings",
    chip: "border-warning/40 text-warning",
    rule: "border-l-warning",
  },
  info: { label: "Notes", chip: "border-line-strong text-info", rule: "border-l-line-strong" },
};

const MAX_ROW_CHIPS = 12;

export function DiagnosticsPanel({ diagnostics, onFocusRow }: Props) {
  const grouped = useMemo(() => {
    const map = new Map<Severity, Diagnostic[]>();
    for (const diagnostic of diagnostics) {
      const list = map.get(diagnostic.severity) ?? [];
      list.push(diagnostic);
      map.set(diagnostic.severity, list);
    }
    return map;
  }, [diagnostics]);

  if (diagnostics.length === 0) {
    return <EmptyState title="No diagnostics">Nothing was flagged in this run.</EmptyState>;
  }

  return (
    <div className="space-y-4">
      {ORDER.filter((severity) => grouped.has(severity)).map((severity) => {
        const tone = TONE[severity];
        const items = grouped.get(severity) ?? [];
        return (
          <section key={severity}>
            <h3 className="text-xs font-semibold text-ink">
              {tone.label}{" "}
              <span className="data font-normal text-info">({items.length})</span>
            </h3>
            <ul className="mt-2 space-y-2">
              {items.map((diagnostic, index) => (
                <li
                  key={`${diagnostic.code}-${index}`}
                  className={`border-l-2 bg-paper px-3 py-2 ${tone.rule}`}
                >
                  <p className="flex flex-wrap items-center gap-2">
                    <span className={`data rounded-md border px-1 py-0.5 text-[0.6875rem] ${tone.chip}`}>
                      {diagnostic.code}
                    </span>
                    {diagnostic.column && (
                      <span className="data text-[0.6875rem] text-info">
                        column {diagnostic.column}
                      </span>
                    )}
                    {diagnostic.target_field && (
                      <span className="data text-[0.6875rem] text-info">
                        field {diagnostic.target_field}
                      </span>
                    )}
                  </p>
                  <p className="mt-1 text-xs text-ink">{diagnostic.message}</p>
                  {diagnostic.rows.length > 0 && (
                    <p className="mt-1.5 flex flex-wrap items-center gap-1">
                      <span className="text-[0.6875rem] text-info">rows</span>
                      {diagnostic.rows.slice(0, MAX_ROW_CHIPS).map((row) => (
                        <button
                          key={row}
                          type="button"
                          onClick={() => onFocusRow(row)}
                          className="data rounded-md border border-line-strong bg-white px-1.5 text-[0.6875rem] text-ink hover:border-accent hover:text-accent-strong"
                        >
                          {row}
                        </button>
                      ))}
                      {diagnostic.rows.length > MAX_ROW_CHIPS && (
                        <span className="data text-[0.6875rem] text-info">
                          +{diagnostic.rows.length - MAX_ROW_CHIPS} more
                        </span>
                      )}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
