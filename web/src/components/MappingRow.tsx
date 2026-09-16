import type { ColumnMapping, SchemaField } from "../lib/types";
import { ConfidenceBar } from "./ConfidenceBar";

interface Props {
  field: SchemaField;
  mapping: ColumnMapping | undefined;
  sourceColumns: string[];
  /** Current (possibly overridden) selection; `null` = deliberately unmapped. */
  selected: string | null;
  onSelect: (sourceColumn: string | null) => void;
  overridden: boolean;
}

const NOT_MAPPED = "— not mapped —";

export function MappingRow({
  field,
  mapping,
  sourceColumns,
  selected,
  onSelect,
  overridden,
}: Props) {
  const ambiguous = mapping?.ambiguous ?? false;
  const missingRequired = field.required && selected === null;
  const selectId = `map-${field.name}`;

  // Ambiguity and unmet required fields are the two things the user must act
  // on, so they get the warning wash and an accent rule down the left edge.
  const rowTone = ambiguous
    ? "bg-warning-wash border-l-2 border-l-warning"
    : missingRequired
      ? "bg-error-wash border-l-2 border-l-error"
      : "border-l-2 border-l-transparent";

  return (
    <tr className={`border-b border-line align-top ${rowTone}`}>
      <td className="px-3 py-2.5">
        <label htmlFor={selectId} className="data block font-medium text-ink">
          {field.name}
        </label>
        <span className="data mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-info">
          <span>{field.field_type}</span>
          {field.required && (
            <span className="rounded-md border border-accent/40 bg-accent-wash px-1 text-accent-strong">
              required
            </span>
          )}
          {ambiguous && (
            <span className="rounded-md border border-warning/40 px-1 text-warning">
              ambiguous
            </span>
          )}
          {overridden && (
            <span className="rounded-md border border-line-strong px-1 text-ink">edited</span>
          )}
        </span>
      </td>

      <td className="px-3 py-2.5">
        <select
          id={selectId}
          value={selected ?? ""}
          onChange={(event) => onSelect(event.target.value === "" ? null : event.target.value)}
          className="data w-56 max-w-full rounded-md border border-line-strong bg-white px-2 py-1 text-ink"
        >
          <option value="">{NOT_MAPPED}</option>
          {sourceColumns.map((column) => (
            <option key={column} value={column}>
              {column}
            </option>
          ))}
        </select>
        {missingRequired && (
          <p className="mt-1 text-[0.6875rem] text-error">
            Required field with no source column.
          </p>
        )}
      </td>

      <td className="px-3 py-2.5">
        {mapping ? (
          <>
            <ConfidenceBar confidence={mapping.confidence} />
            <span className="data mt-0.5 block text-[0.6875rem] text-info">
              {mapping.method}
            </span>
          </>
        ) : (
          <span className="data text-[0.6875rem] text-info">no proposal</span>
        )}
      </td>

      <td className="px-3 py-2.5 text-xs text-info">
        {mapping?.rationale ?? <span className="text-info/70">No rationale given.</span>}
      </td>

      <td className="px-3 py-2.5">
        {mapping && mapping.alternatives.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {mapping.alternatives.map((alternative) => (
              <li key={alternative.source_column}>
                <button
                  type="button"
                  title={alternative.rationale ?? undefined}
                  aria-pressed={selected === alternative.source_column}
                  onClick={() => onSelect(alternative.source_column)}
                  className={[
                    "data flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 transition-colors",
                    selected === alternative.source_column
                      ? "border-accent bg-accent-wash text-accent-strong"
                      : "border-line-strong bg-white text-ink hover:border-accent/50",
                  ].join(" ")}
                >
                  <span>{alternative.source_column}</span>
                  <ConfidenceBar confidence={alternative.confidence} compact />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <span className="data text-[0.6875rem] text-info">—</span>
        )}
      </td>
    </tr>
  );
}
