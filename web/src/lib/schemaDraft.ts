/**
 * The editor's working copy of a schema, plus the validation that mirrors the
 * server's 422 rules. Kept out of the components so the editor screen stays a
 * thin shell over `draft -> validate -> toWrite`.
 */
import type { FieldType, SchemaOut, SchemaTemplateField, SchemaWrite } from "./types";

/** The contract's closed set, in the order the contract lists them. */
export const FIELD_TYPES: readonly FieldType[] = [
  "string",
  "email",
  "phone",
  "number",
  "integer",
  "date",
  "boolean",
];

/**
 * A row being edited. `key` is a client-only React identity: field names are
 * editable (and may be briefly blank or duplicated mid-typing), so they cannot
 * serve as list keys without rows losing focus as you type.
 */
export interface DraftField {
  key: string;
  name: string;
  field_type: FieldType;
  required: boolean;
  description: string;
}

export interface SchemaDraft {
  name: string;
  description: string;
  fields: DraftField[];
}

let keyCounter = 0;

export function blankField(): DraftField {
  keyCounter += 1;
  return {
    key: `f${keyCounter}`,
    name: "",
    field_type: "string",
    required: false,
    description: "",
  };
}

/** A new schema opens with one row, so the screen is never an empty page. */
export function emptyDraft(): SchemaDraft {
  return { name: "", description: "", fields: [blankField()] };
}

function toDraftField(field: SchemaTemplateField): DraftField {
  return {
    key: blankField().key,
    name: field.name,
    field_type: field.field_type,
    required: field.required,
    description: field.description ?? "",
  };
}

export function draftFromSchema(schema: SchemaOut): SchemaDraft {
  return {
    name: schema.name,
    description: schema.description ?? "",
    // Sort on the way in so the array order the editor manipulates already
    // matches the order the server means.
    fields: [...schema.fields].sort((a, b) => a.position - b.position).map(toDraftField),
  };
}

/**
 * `position` is derived from array order rather than typed in: two sources of
 * truth for order (an index and a number the user maintains) can disagree, and
 * the disagreement is invisible until an export comes out shuffled. Move
 * up/down rewrites the array; the index is authoritative at save time.
 */
export function toWrite(draft: SchemaDraft): SchemaWrite {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || undefined,
    fields: draft.fields.map((field, index) => ({
      name: field.name.trim(),
      field_type: field.field_type,
      required: field.required,
      description: field.description.trim() || undefined,
      position: index,
    })),
  };
}

/** Swaps a row with its neighbour; a no-op at either end. */
export function moveField(fields: DraftField[], index: number, delta: -1 | 1): DraftField[] {
  const target = index + delta;
  if (target < 0 || target >= fields.length) return fields;
  const next = [...fields];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export interface DraftErrors {
  /** Shown against the name input, including the server's 409. */
  name: string | null;
  /** Keyed by `DraftField.key`, shown inline on the offending row. */
  fields: Record<string, string>;
  /** Applies to the field list as a whole. */
  fieldList: string | null;
}

/**
 * Mirrors the server's 422 rules so the user is told before a round trip.
 * The server stays the authority; this only avoids predictable rejections.
 */
export function validateDraft(draft: SchemaDraft): DraftErrors {
  const fields: Record<string, string> = {};

  const counts = new Map<string, number>();
  for (const field of draft.fields) {
    const key = field.name.trim().toLowerCase();
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  for (const field of draft.fields) {
    const name = field.name.trim();
    if (!name) {
      fields[field.key] = "Every field needs a name.";
    } else if ((counts.get(name.toLowerCase()) ?? 0) > 1) {
      // Case-insensitive, because two fields differing only in case would be
      // indistinguishable in a mapping table and in most exports.
      fields[field.key] = "Duplicate field name.";
    }
  }

  return {
    name: draft.name.trim() ? null : "Give the schema a name.",
    fields,
    fieldList: draft.fields.length === 0 ? "A schema needs at least one field." : null,
  };
}

export function hasErrors(errors: DraftErrors): boolean {
  return Boolean(errors.name || errors.fieldList) || Object.keys(errors.fields).length > 0;
}
