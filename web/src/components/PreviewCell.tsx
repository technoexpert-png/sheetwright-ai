import type { ResultCell } from "../lib/types";
import { cellKind, cellText } from "../lib/format";

/**
 * "No column" and "empty" are different failures and must read differently:
 *   - no column  -> the schema field has no source at all (hatched, italic)
 *   - empty      -> a column is mapped but this row had no value (dashed, quiet)
 *   - value      -> plain tabular text
 * Collapsing the two would hide whether the fix is a mapping change or a data
 * change, which is the distinction this whole screen exists to surface.
 */
export function PreviewCell({ cell }: { cell: ResultCell | undefined }) {
  const kind = cellKind(cell);

  if (kind === "unmapped") {
    return (
      <td
        title={cell?.reason ?? "No source column mapped to this field."}
        className="data border-b border-line bg-[repeating-linear-gradient(135deg,#f5f5f4_0,#f5f5f4_4px,#ffffff_4px,#ffffff_8px)] px-3 py-1.5 whitespace-nowrap text-info italic"
      >
        no column
      </td>
    );
  }

  if (kind === "empty") {
    return (
      <td
        title={cell?.reason ?? `Column "${cell?.source_column ?? "?"}" was blank for this row.`}
        className="data border-b border-line px-3 py-1.5 whitespace-nowrap"
      >
        <span className="rounded-md border border-dashed border-line-strong px-1.5 text-[0.6875rem] text-info">
          empty
        </span>
      </td>
    );
  }

  return (
    <td
      title={cell?.source_column ? `from ${cell.source_column}` : undefined}
      className="data max-w-64 truncate border-b border-line px-3 py-1.5 text-ink"
    >
      {cell ? cellText(cell) : ""}
    </td>
  );
}
