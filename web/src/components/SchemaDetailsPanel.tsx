import { Panel } from "./Panel";
import { TextField } from "./TextField";

interface Props {
  name: string;
  description: string;
  /** Includes the server's 409, which belongs on the name input specifically. */
  nameError: string | null;
  disabled: boolean;
  onChange: (changes: { name?: string; description?: string }) => void;
}

export function SchemaDetailsPanel({
  name,
  description,
  nameError,
  disabled,
  onChange,
}: Props) {
  return (
    <Panel title="Details">
      <div className="space-y-4">
        <TextField
          label="Name"
          value={name}
          required
          spellCheck={false}
          placeholder="Customer contacts"
          disabled={disabled}
          error={nameError}
          hint="Unique within your organisation."
          onChange={(event) => onChange({ name: event.target.value })}
        />
        <div>
          <label
            htmlFor="schema-description"
            className="block text-xs font-semibold text-ink"
          >
            Description
          </label>
          <textarea
            id="schema-description"
            rows={2}
            value={description}
            disabled={disabled}
            placeholder="What kind of file is mapped onto this schema?"
            onChange={(event) => onChange({ description: event.target.value })}
            className="data mt-1.5 w-full resize-y rounded-md border border-line-strong bg-white px-2 py-1.5 text-ink"
          />
        </div>
      </div>
    </Panel>
  );
}
