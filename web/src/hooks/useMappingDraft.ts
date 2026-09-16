import { useCallback, useMemo, useState } from "react";
import type { ResultOut } from "../lib/types";

export interface MappingDraft {
  /** field -> source column (null = deliberately not mapped). */
  draft: Record<string, string | null>;
  changedFields: string[];
  set: (field: string, sourceColumn: string | null) => void;
  reset: () => void;
  /** Full mapping payload for PUT /uploads/{id}/mapping. */
  payload: Record<string, string | null>;
}

function baseline(result: ResultOut | null): Record<string, string | null> {
  if (!result) return {};
  const entries = result.schema.fields.map((field) => [
    field.name,
    result.column_mapping[field.name]?.source_column ?? null,
  ]);
  return Object.fromEntries(entries) as Record<string, string | null>;
}

/**
 * Holds the user's edits over the model's proposal. Every schema field is sent
 * on re-run, not just the edited ones, so the server never has to merge a
 * partial mapping against a stale revision.
 */
export function useMappingDraft(result: ResultOut | null): MappingDraft {
  const original = useMemo(() => baseline(result), [result]);
  // A new result object (new revision, or another page of rows) is a new
  // baseline. Adjusting during render — rather than in an effect — means the
  // table never paints one frame of the previous upload's mapping.
  const [state, setState] = useState({ source: result, draft: original });
  if (state.source !== result) setState({ source: result, draft: original });
  const draft = state.source === result ? state.draft : original;

  const set = useCallback(
    (field: string, sourceColumn: string | null) =>
      setState((current) => ({
        ...current,
        draft: { ...current.draft, [field]: sourceColumn },
      })),
    [],
  );

  const reset = useCallback(
    () => setState({ source: result, draft: original }),
    [result, original],
  );

  const changedFields = useMemo(
    () => Object.keys(original).filter((field) => draft[field] !== original[field]),
    [draft, original],
  );

  return { draft, changedFields, set, reset, payload: draft };
}
