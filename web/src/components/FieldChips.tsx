import type { SchemaTemplateField } from "../lib/types";

/**
 * A schema's fields at a glance. Monospace because a field name is an
 * identifier that must be compared character by character, not read as prose.
 */
export function FieldChips({ fields }: { fields: SchemaTemplateField[] }) {
  if (fields.length === 0) {
    return <p className="data text-[0.6875rem] text-info">no fields</p>;
  }

  return (
    <ul className="flex flex-wrap gap-1.5">
      {fields.map((field) => (
        <li
          key={field.name}
          title={field.description ?? undefined}
          className="data flex items-baseline gap-1.5 rounded-md border border-line bg-paper px-1.5 py-0.5"
        >
          <span className="text-ink">{field.name}</span>
          <span className="text-[0.6875rem] text-info">{field.field_type}</span>
          {field.required && <span className="text-[0.6875rem] text-accent">req</span>}
        </li>
      ))}
    </ul>
  );
}
