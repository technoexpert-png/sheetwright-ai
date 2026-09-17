import { Button } from "./Button";
import { Panel } from "./Panel";
import { SchemaFieldRow } from "./SchemaFieldRow";
import { blankField, moveField, type DraftErrors, type DraftField } from "../lib/schemaDraft";

interface Props {
  fields: DraftField[];
  errors: DraftErrors;
  disabled: boolean;
  onChange: (fields: DraftField[]) => void;
}

/** Why the description matters, stated once above the rows rather than repeated. */
function DescriptionNote() {
  return (
    <div className="mb-4 rounded-md border border-accent/30 bg-accent-wash px-3 py-2.5">
      <p className="text-xs font-semibold text-accent-strong">
        Descriptions do the mapping work
      </p>
      <p className="mt-1 max-w-prose text-xs text-ink">
        The mapper reads each field's description to decide which column in an uploaded
        file belongs to it. A field named <span className="data">email</span> cannot say
        which email it wants; a description can.
      </p>
      <p className="data mt-2 text-[0.6875rem] text-info">
        email → “Work email address, not a personal one.”
      </p>
    </div>
  );
}

export function SchemaFieldList({ fields, errors, disabled, onChange }: Props) {
  function patch(index: number, changes: Partial<DraftField>) {
    onChange(fields.map((field, i) => (i === index ? { ...field, ...changes } : field)));
  }

  return (
    <Panel
      title="Fields"
      description="The columns your uploads are mapped onto, in export order."
      actions={
        <Button
          type="button"
          disabled={disabled}
          onClick={() => onChange([...fields, blankField()])}
        >
          Add field
        </Button>
      }
    >
      <DescriptionNote />

      {errors.fieldList ? (
        <p role="alert" className="text-xs text-error">
          {errors.fieldList}
        </p>
      ) : (
        <ul className="space-y-2.5">
          {fields.map((field, index) => (
            <SchemaFieldRow
              key={field.key}
              field={field}
              index={index}
              total={fields.length}
              error={errors.fields[field.key]}
              disabled={disabled}
              onChange={(changes) => patch(index, changes)}
              // Position is never typed in: it is the array index at save
              // time, so reordering is the only way to change it.
              onMove={(delta) => onChange(moveField(fields, index, delta))}
              onRemove={() => onChange(fields.filter((_, i) => i !== index))}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}
