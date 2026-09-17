import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { describeError, isDuplicateName, schemas as schemasApi } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { SessionGate } from "../components/SessionGate";
import { Button } from "../components/Button";
import { SchemaDetailsPanel } from "../components/SchemaDetailsPanel";
import { ErrorState, LoadingState } from "../components/StateBlocks";
import { SchemaFieldList } from "../components/SchemaFieldList";
import { DeleteSchemaCard } from "../components/DeleteSchemaCard";
import {
  draftFromSchema,
  emptyDraft,
  hasErrors,
  toWrite,
  validateDraft,
  type DraftErrors,
  type SchemaDraft,
} from "../lib/schemaDraft";

const NO_ERRORS: DraftErrors = { name: null, fields: {}, fieldList: null };

/** One component for `/schemas/new` and `/schemas/:id`; `new` starts empty. */
function SchemaEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const existing = useAsync(() => (id ? schemasApi.get(id) : Promise.resolve(null)), [id]);

  const [draft, setDraft] = useState<SchemaDraft>(emptyDraft);
  // Validation is live, but only after the first edit: a brand-new schema
  // should not open covered in red for things the user has not tried yet.
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameConflict, setNameConflict] = useState<string | null>(null);

  useEffect(() => {
    if (existing.data) setDraft(draftFromSchema(existing.data));
  }, [existing.data]);

  useEffect(() => {
    // Moving from an existing schema to /schemas/new must not inherit its draft.
    if (!id) setDraft(emptyDraft());
    setTouched(false);
    setSaved(false);
  }, [id]);

  const errors = useMemo(() => validateDraft(draft), [draft]);
  const shown = touched ? errors : NO_ERRORS;
  const blocked = saving || hasErrors(errors);

  function edit(changes: Partial<SchemaDraft>) {
    setTouched(true);
    setSaved(false);
    setNameConflict(null);
    setDraft((current) => ({ ...current, ...changes }));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    // Belt and braces with the disabled button: Enter in a text input submits
    // too, and a slow POST must never be fired twice.
    if (blocked) return;
    setSaving(true);
    setSaveError(null);
    setNameConflict(null);
    try {
      const body = toWrite(draft);
      const result = id ? await schemasApi.update(id, body) : await schemasApi.create(body);
      setTouched(false);
      setSaved(true);
      // A freshly created schema gets its own URL, so reload, delete and
      // subsequent saves all act on the thing that now exists.
      if (id) setDraft(draftFromSchema(result));
      else navigate(`/schemas/${result.id}`, { replace: true });
    } catch (cause) {
      if (isDuplicateName(cause)) {
        setNameConflict("A schema with that name already exists.");
      } else {
        setSaveError(describeError(cause));
      }
    } finally {
      setSaving(false);
    }
  }

  async function remove(schemaId: string) {
    await schemasApi.remove(schemaId);
    navigate("/schemas", { replace: true });
  }

  if (id && existing.loading) return <LoadingState label="Loading this schema…" />;
  if (id && existing.error) {
    return (
      <ErrorState
        title="Could not load this schema"
        message={existing.error}
        hint={<Link to="/schemas" className="text-accent underline">Back to schemas</Link>}
        onRetry={existing.reload}
      />
    );
  }

  return (
    <form className="max-w-3xl space-y-4" onSubmit={save} noValidate>
      <div>
        <Link to="/schemas" className="text-xs text-info underline">
          ← Schemas
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-ink">
          {id ? existing.data?.name ?? "Schema" : "New schema"}
        </h1>
      </div>

      <SchemaDetailsPanel
        name={draft.name}
        description={draft.description}
        nameError={nameConflict ?? shown.name}
        disabled={saving}
        onChange={edit}
      />

      <SchemaFieldList
        fields={draft.fields}
        errors={shown}
        disabled={saving}
        onChange={(fields) => edit({ fields })}
      />

      {saveError && <ErrorState title="Could not save" message={saveError} />}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={blocked}>
          {saving ? "Saving…" : id ? "Save changes" : "Create schema"}
        </Button>
        {hasErrors(errors) ? (
          <span className="text-xs text-info">
            Needs a name and at least one field, each with a unique name.
          </span>
        ) : (
          saved && (
            <span role="status" className="text-xs text-accent-strong">
              Saved.
            </span>
          )
        )}
      </div>

      {id && (
        <DeleteSchemaCard schemaName={draft.name} onDelete={() => remove(id)} />
      )}
    </form>
  );
}

export function SchemaEditorPage() {
  return (
    <SessionGate>
      <SchemaEditor />
    </SessionGate>
  );
}
