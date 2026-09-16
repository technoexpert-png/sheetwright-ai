import { Fragment, useState } from "react";
import type { ResultOut, SchemaField } from "../lib/types";
import { PreviewCell } from "./PreviewCell";
import { EmptyState } from "./StateBlocks";

interface Props {
  result: ResultOut;
  /** Source row the diagnostics panel asked us to jump to. */
  focusedRow: number | null;
  registerRow: (sourceRow: number, element: HTMLTableRowElement | null) => void;
}

export function PreviewTable({ result, focusedRow, registerRow }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const fields: SchemaField[] = [...result.schema.fields].sort(
    (a, b) => a.position - b.position,
  );

  if (result.rows.length === 0) {
    return <EmptyState title="No rows to preview">This run produced no data rows.</EmptyState>;
  }

  return (
    <div className="max-h-[32rem] overflow-auto">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Mapped data preview</caption>
        <thead className="sticky top-0 z-10 bg-white">
          <tr className="border-b border-line-strong">
            <th scope="col" className="px-3 pb-2 text-xs font-semibold text-info">
              row
            </th>
            <th scope="col" className="px-3 pb-2 text-xs font-semibold text-info">
              !
            </th>
            {fields.map((field) => (
              <th
                key={field.name}
                scope="col"
                className="data px-3 pb-2 text-xs font-semibold whitespace-nowrap text-info"
              >
                {field.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row) => {
            const focused = focusedRow === row.source_row;
            const open = expanded === row.source_row;
            return (
              <Fragment key={row.source_row}>
                <tr
                  ref={(element) => registerRow(row.source_row, element)}
                  className={focused ? "bg-accent-wash" : undefined}
                >
                  <td className="data border-b border-line px-3 py-1.5 text-info">
                    {row.source_row}
                  </td>
                  <td className="border-b border-line px-3 py-1.5">
                    {row.warnings.length > 0 ? (
                      <button
                        type="button"
                        aria-expanded={open}
                        title={row.warnings.join("\n")}
                        onClick={() => setExpanded(open ? null : row.source_row)}
                        className="data rounded-md border border-warning/40 bg-warning-wash px-1 text-[0.6875rem] text-warning hover:border-warning"
                      >
                        {row.warnings.length}
                      </button>
                    ) : (
                      <span className="data text-[0.6875rem] text-line-strong">·</span>
                    )}
                  </td>
                  {fields.map((field) => (
                    <PreviewCell key={field.name} cell={row.fields[field.name]} />
                  ))}
                </tr>
                {open && (
                  <tr className="bg-warning-wash">
                    <td colSpan={fields.length + 2} className="px-3 py-2">
                      <ul className="space-y-0.5 text-xs text-warning">
                        {row.warnings.map((warning, index) => (
                          <li key={index}>{warning}</li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
