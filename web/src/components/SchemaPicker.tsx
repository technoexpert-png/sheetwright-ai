import type { SchemaOut } from "../lib/types";

interface Props {
  schemas: SchemaOut[];
  value: string;
  onChange: (schemaId: string) => void;
  disabled?: boolean;
}

export function SchemaPicker({ schemas, value, onChange, disabled }: Props) {
  const selected = schemas.find((schema) => schema.id === value) ?? null;

  return (
    <div>
      <label htmlFor="schema" className="block text-xs font-semibold text-ink">
        Target schema
      </label>
      <select
        id="schema"
        name="schema_id"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="data mt-1.5 w-full rounded-md border border-line-strong bg-white px-2 py-1.5 text-ink disabled:opacity-50"
      >
        {schemas.map((schema) => (
          <option key={schema.id} value={schema.id}>
            {schema.name}
          </option>
        ))}
      </select>

      {selected && (
        <div className="mt-3">
          {selected.description && (
            <p className="text-xs text-info">{selected.description}</p>
          )}
          <p className="mt-2 text-xs font-semibold text-ink">
            {selected.fields.length} field{selected.fields.length === 1 ? "" : "s"}
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {[...selected.fields]
              .sort((a, b) => a.position - b.position)
              .map((field) => (
                <li
                  key={field.name}
                  title={field.description ?? undefined}
                  className="data flex items-baseline gap-1.5 rounded-md border border-line bg-paper px-1.5 py-0.5"
                >
                  <span className="text-ink">{field.name}</span>
                  <span className="text-[0.6875rem] text-info">{field.field_type}</span>
                  {field.required && (
                    <span className="text-[0.6875rem] text-accent">req</span>
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
