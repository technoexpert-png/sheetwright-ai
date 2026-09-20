import { useId } from "react";
import { FIELD_TYPES, type DraftField } from "../lib/schemaDraft";

interface Props {
  field: DraftField;
  index: number;
  total: number;
  /** Inline validation message for this row, if any. */
  error?: string;
  disabled: boolean;
  onChange: (patch: Partial<DraftField>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}

const INPUT =
  "data w-full rounded-md border border-line-strong bg-white px-2 py-1.5 text-ink disabled:bg-paper disabled:text-info";

const ICON_BUTTON =
  "rounded-md border border-line px-1.5 py-1 text-xs text-info transition-colors hover:border-line-strong hover:text-ink disabled:cursor-not-allowed disabled:border-line disabled:text-info/40";

export function SchemaFieldRow({
  field,
  index,
  total,
  error,
  disabled,
  onChange,
  onMove,
  onRemove,
}: Props) {
  const id = useId();
  const nameId = `${id}-name`;
  const typeId = `${id}-type`;
  const requiredId = `${id}-required`;
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const label = field.name.trim() || `field ${index + 1}`;

  return (
    <li
      className={`rounded-md border bg-white p-3 ${error ? "border-error/40" : "border-line"}`}
    >
      <div className="flex flex-wrap items-end gap-3">
        <span className="data pb-1.5 text-[0.6875rem] text-info" aria-hidden="true">
          {String(index + 1).padStart(2, "0")}
        </span>

        <div className="min-w-44 flex-1">
          <label htmlFor={nameId} className="block text-xs font-semibold text-ink">
            Field name
          </label>
          <input
            id={nameId}
            value={field.name}
            disabled={disabled}
            spellCheck={false}
            placeholder="work_email"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => onChange({ name: event.target.value })}
            className={`mt-1.5 ${INPUT}`}
          />
        </div>

        <div className="w-36">
          <label htmlFor={typeId} className="block text-xs font-semibold text-ink">
            Type
          </label>
          <select
            id={typeId}
            value={field.field_type}
            disabled={disabled}
            onChange={(event) =>
              onChange({ field_type: event.target.value as DraftField["field_type"] })
            }
            className={`mt-1.5 ${INPUT}`}
          >
            {FIELD_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        <label
          htmlFor={requiredId}
          className="flex items-center gap-1.5 pb-1.5 text-xs font-semibold text-ink"
        >
          <input
            id={requiredId}
            type="checkbox"
            checked={field.required}
            disabled={disabled}
            onChange={(event) => onChange({ required: event.target.checked })}
            className="size-3.5 accent-accent"
          />
          Required
        </label>

        <div className="ml-auto flex items-center gap-1 pb-1">
          <button
            type="button"
            aria-label={`Move ${label} up`}
            disabled={disabled || index === 0}
            onClick={() => onMove(-1)}
            className={ICON_BUTTON}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label={`Move ${label} down`}
            disabled={disabled || index === total - 1}
            onClick={() => onMove(1)}
            className={ICON_BUTTON}
          >
            ↓
          </button>
          <button
            type="button"
            aria-label={`Remove ${label}`}
            disabled={disabled}
            onClick={onRemove}
            className={`${ICON_BUTTON} hover:border-error/40 hover:text-error`}
          >
            Remove
          </button>
        </div>
      </div>

      {error && (
        <p id={errorId} role="alert" className="mt-2 text-xs text-error">
          {error}
        </p>
      )}

      {/* The description carries more weight than anything else on this row —
          it is what the mapper reasons over — so it gets the accent rule and
          an example rather than sitting in the row as a gray afterthought. */}
      <div className="mt-3 border-l-2 border-l-accent bg-accent-wash/60 p-2.5">
        <label htmlFor={descriptionId} className="block text-xs font-semibold text-ink">
          Description{" "}
          <span className="font-normal text-accent-strong">what the mapper reads</span>
        </label>
        <textarea
          id={descriptionId}
          rows={2}
          value={field.description}
          disabled={disabled}
          placeholder="Work email address, not a personal one."
          onChange={(event) => onChange({ description: event.target.value })}
          className={`mt-1.5 resize-y ${INPUT}`}
        />
      </div>
    </li>
  );
}
