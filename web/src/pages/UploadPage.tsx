import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { describeError, schemas as schemasApi, uploads } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { useSession } from "../context/SessionContext";
import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import { FileDrop } from "../components/FileDrop";
import { SchemaPicker } from "../components/SchemaPicker";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";

export function UploadPage() {
  const navigate = useNavigate();
  const { session, loading: sessionLoading, error: sessionError, ensureTrial } = useSession();
  const authenticated = session?.authenticated ?? false;

  // Schemas are tenant data, so asking for them before a session exists returns
  // 401 — which this page then rendered as "Could not load schemas: Not
  // authenticated": alarming on a first visit, and describing the wrong
  // problem. Gate the fetch on the session and re-run when it appears (or
  // changes at signup, which swaps the org).
  const schemaList = useAsync(
    () => (authenticated ? schemasApi.list() : Promise.resolve(null)),
    [authenticated],
  );
  const [schemaId, setSchemaId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Uploading requires a session, and the contract lets us mint an anonymous
  // one. Do it on arrival so the header can show the org and the trial notice
  // before the user commits a file.
  useEffect(() => {
    if (session && !session.authenticated) void ensureTrial();
  }, [session, ensureTrial]);

  // Derived rather than synced into state: the first schema is the default
  // until the user picks one, so there is nothing to keep in step.
  const selectedSchemaId = schemaId || (schemaList.data?.[0]?.id ?? "");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !selectedSchemaId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const upload = await uploads.create(file, selectedSchemaId);
      navigate(`/u/${upload.id}`);
    } catch (cause) {
      setSubmitError(describeError(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="space-y-4">
        <div>
          <h1 className="text-lg font-semibold text-ink">Map a spreadsheet to a schema</h1>
          <p className="mt-1 max-w-prose text-sm text-info">
            Upload the file as it is. Sheetwright proposes a column mapping, tells you how
            confident it is about each field, and hands you the review before anything is
            exported.
          </p>
        </div>

        <Panel title="New upload">
          {/* A trial is minted on arrival, so the honest first state is
              "starting up", not "failed to load". */}
          {sessionError && (
            <ErrorState
              title="Could not start a session"
              message={sessionError}
              onRetry={() => void ensureTrial()}
            />
          )}

          {!sessionError && !authenticated && (
            <LoadingState
              label={sessionLoading ? "Checking your session…" : "Preparing your workspace…"}
            />
          )}

          {authenticated && schemaList.loading && (
            <LoadingState label="Loading target schemas…" />
          )}

          {authenticated && schemaList.error && (
            <ErrorState
              title="Could not load schemas"
              message={schemaList.error}
              onRetry={schemaList.reload}
            />
          )}

          {schemaList.data && schemaList.data.length === 0 && (
            <EmptyState title="No schemas available yet">
              This organisation has no target schemas configured, so there is nothing to map
              onto.
            </EmptyState>
          )}

          {schemaList.data && schemaList.data.length > 0 && (
            <form className="space-y-5" onSubmit={submit}>
              <SchemaPicker
                schemas={schemaList.data}
                value={selectedSchemaId}
                onChange={setSchemaId}
                disabled={submitting}
              />
              <FileDrop file={file} onSelect={setFile} disabled={submitting} />

              {submitError && <ErrorState title="Upload failed" message={submitError} />}

              <div className="flex items-center gap-3">
                <Button type="submit" variant="primary" disabled={!file || submitting}>
                  {submitting ? "Uploading…" : "Upload and map"}
                </Button>
                <span className="text-xs text-info">
                  You will land on the review step, not on a finished file.
                </span>
              </div>
            </form>
          )}
        </Panel>

      </div>

      <aside className="space-y-3">
        <Panel title="How it works">
          <ol className="space-y-3 text-xs text-info">
            <li>
              <span className="data text-accent">01</span> We read every header in your file.
            </li>
            <li>
              <span className="data text-accent">02</span> An LLM proposes a source column for
              each schema field, with a confidence score and alternatives.
            </li>
            <li>
              <span className="data text-accent">03</span> You review, override anything, and
              re-run.
            </li>
            <li>
              <span className="data text-accent">04</span> Export as CSV, XLSX or JSON.
            </li>
          </ol>
        </Panel>
        <Panel title="Earlier uploads">
          <p className="text-xs text-info">
            Every upload stays in your{" "}
            <Link to="/uploads" className="text-accent underline">
              history
            </Link>
            , with the mapping that produced it.
          </p>
        </Panel>
      </aside>
    </div>
  );
}
