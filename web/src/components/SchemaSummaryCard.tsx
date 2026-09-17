import { Link } from "react-router-dom";
import { FieldChips } from "./FieldChips";
import type { SchemaOut } from "../lib/types";

export function SchemaSummaryCard({ schema }: { schema: SchemaOut }) {
  // The server owns `position`; the list renders in that order rather than in
  // whatever order the JSON happened to arrive.
  const fields = [...schema.fields].sort((a, b) => a.position - b.position);

  return (
    <li className="rounded-md border border-line bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">{schema.name}</h2>
        <Link
          to={`/schemas/${schema.id}`}
          className="rounded-md border border-line-strong px-2 py-0.5 text-xs text-ink transition-colors hover:border-ink/40 hover:bg-paper"
        >
          Edit
        </Link>
      </div>

      <p className="mt-1 text-xs text-info">
        {schema.description || "No description."}
      </p>

      <p className="data mt-3 text-[0.6875rem] text-info">
        {fields.length} field{fields.length === 1 ? "" : "s"}
        {schema.from_template && <> · from template {schema.from_template}</>}
      </p>

      <div className="mt-1.5">
        <FieldChips fields={fields} />
      </div>
    </li>
  );
}
