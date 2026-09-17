import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { schemas as schemasApi } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import { SessionGate } from "../components/SessionGate";
import { SchemaSummaryCard } from "../components/SchemaSummaryCard";
import { TemplateGallery } from "../components/TemplateGallery";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";

function SchemaList() {
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(() => schemasApi.list(), []);
  const [showTemplates, setShowTemplates] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Target schemas</h1>
          <p className="mt-1 max-w-prose text-sm text-info">
            The shapes your uploads are mapped onto. Field descriptions are what the
            mapper reasons over, so they are worth writing carefully.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={() => setShowTemplates((open) => !open)}>
            Start from a template
          </Button>
          <Button type="button" variant="primary" onClick={() => navigate("/schemas/new")}>
            New schema
          </Button>
        </div>
      </div>

      {showTemplates && (
        <TemplateGallery
          onClose={() => setShowTemplates(false)}
          // Straight into the editor: a copied template is a starting point,
          // and its descriptions are generic until the user adjusts them.
          onCreated={(schema) => navigate(`/schemas/${schema.id}`)}
        />
      )}

      {loading && (
        <Panel>
          <LoadingState label="Loading your schemas…" />
        </Panel>
      )}

      {error && (
        <ErrorState title="Could not load schemas" message={error} onRetry={reload} />
      )}

      {data && data.length === 0 && !showTemplates && (
        <EmptyState title="No schemas yet">
          <p>
            Create one from scratch, or copy a template and edit it.{" "}
            <Link to="/schemas/new" className="text-accent underline">
              New schema
            </Link>
          </p>
        </EmptyState>
      )}

      {data && data.length > 0 && (
        <ul className="grid gap-3 lg:grid-cols-2">
          {data.map((schema) => (
            <SchemaSummaryCard key={schema.id} schema={schema} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function SchemasPage() {
  return (
    <SessionGate>
      <SchemaList />
    </SessionGate>
  );
}
