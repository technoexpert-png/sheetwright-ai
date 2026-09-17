import { useState } from "react";
import { describeError, schemas as schemasApi } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { Button } from "./Button";
import { Panel } from "./Panel";
import { FieldChips } from "./FieldChips";
import { EmptyState, ErrorState, LoadingState } from "./StateBlocks";
import type { SchemaOut } from "../lib/types";

interface Props {
  /** Called with the schema the server created from the chosen template. */
  onCreated: (schema: SchemaOut) => void;
  onClose: () => void;
}

export function TemplateGallery({ onCreated, onClose }: Props) {
  const { data, error, loading, reload } = useAsync(() => schemasApi.templates(), []);
  // Holds the key being copied, which doubles as the "in flight" flag: one
  // click can only ever produce one schema.
  const [creating, setCreating] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  async function copy(key: string) {
    if (creating) return;
    setCreating(key);
    setCreateError(null);
    try {
      onCreated(await schemasApi.createFromTemplate(key));
    } catch (cause) {
      setCreateError(describeError(cause));
      setCreating(null);
    }
  }

  const entries = Object.entries(data ?? {});

  return (
    <Panel
      title="Start from a template"
      description="Copied into your organisation, then yours to edit."
      actions={
        <Button type="button" variant="quiet" onClick={onClose}>
          Close
        </Button>
      }
    >
      {loading && <LoadingState label="Loading templates…" />}
      {error && <ErrorState title="Could not load templates" message={error} onRetry={reload} />}
      {createError && <ErrorState title="Could not copy template" message={createError} />}
      {data && entries.length === 0 && <EmptyState title="No templates available." />}

      {entries.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {entries.map(([key, template]) => (
            <li key={key} className="rounded-md border border-line p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-ink">{template.name}</h3>
                <span className="data text-[0.6875rem] text-info">{key}</span>
              </div>
              {template.description && (
                <p className="mt-1 text-xs text-info">{template.description}</p>
              )}
              <div className="mt-2">
                <FieldChips fields={template.fields} />
              </div>
              <Button
                type="button"
                variant="primary"
                className="mt-3"
                disabled={creating !== null}
                onClick={() => void copy(key)}
              >
                {creating === key ? "Creating…" : "Use this template"}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
