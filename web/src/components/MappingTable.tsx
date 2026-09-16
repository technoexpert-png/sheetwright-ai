import { useMemo } from "react";
import type { ResultOut } from "../lib/types";
import { MappingRow } from "./MappingRow";

interface Props {
  result: ResultOut;
  /** field -> selected source column (null = not mapped). */
  draft: Record<string, string | null>;
  onSelect: (field: string, sourceColumn: string | null) => void;
}

const HEADERS = ["Schema field", "Source column", "Confidence", "Why", "Alternatives"];

export function MappingTable({ result, draft, onSelect }: Props) {
  const fields = useMemo(() => {
    const original = result.column_mapping;
    // Ambiguous rows sort to the top because reviewing them IS the task: the
    // user should never have to hunt through confident rows to find the two
    // the model was unsure about. Unmet required fields rank alongside them,
    // then low confidence, then schema order for everything settled.
    return [...result.schema.fields].sort((a, b) => {
      const rank = (name: string, required: boolean) => {
        const mapping = original[name];
        if (mapping?.ambiguous) return 0;
        if (required && (draft[name] ?? null) === null) return 1;
        if (mapping && mapping.confidence < 0.5) return 2;
        return 3;
      };
      const delta = rank(a.name, a.required) - rank(b.name, b.required);
      return delta !== 0 ? delta : a.position - b.position;
    });
  }, [result.schema.fields, result.column_mapping, draft]);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-left">
        <caption className="sr-only">
          Proposed column mapping, ambiguous fields first
        </caption>
        <thead>
          <tr className="border-b border-line-strong">
            {HEADERS.map((header) => (
              <th
                key={header}
                scope="col"
                className="px-3 pb-2 text-xs font-semibold text-info"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => {
            const mapping = result.column_mapping[field.name];
            const selected = field.name in draft ? draft[field.name] : (mapping?.source_column ?? null);
            return (
              <MappingRow
                key={field.name}
                field={field}
                mapping={mapping}
                sourceColumns={result.source_columns}
                selected={selected}
                onSelect={(value) => onSelect(field.name, value)}
                overridden={selected !== (mapping?.source_column ?? null)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
