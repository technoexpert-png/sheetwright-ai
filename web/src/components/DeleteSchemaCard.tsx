import { useState } from "react";
import { describeError } from "../lib/api";
import { Button } from "./Button";
import { Panel } from "./Panel";
import { ErrorState } from "./StateBlocks";

interface Props {
  schemaName: string;
  /** Resolves only if the schema is gone; rejections surface in this card. */
  onDelete: () => Promise<void>;
}

/**
 * Deletion is confirmed in place rather than in a modal, because the thing the
 * user needs in order to decide is a sentence, not a choice: the contract
 * guarantees past uploads survive, and saying so removes the actual fear.
 */
export function DeleteSchemaCard({ schemaName, onDelete }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await onDelete();
    } catch (cause) {
      // Left in the deleting=false state so the user can retry; on success the
      // editor navigates away and this card unmounts.
      setError(describeError(cause));
      setDeleting(false);
    }
  }

  return (
    <Panel title="Delete this schema">
      {error && <ErrorState title="Could not delete" message={error} />}

      <p className="max-w-prose text-xs text-info">
        Existing uploads keep working. Each stored result carries its own copy of the
        schema it was mapped against, so past runs stay readable and exportable after
        this one is gone. Only new uploads lose it as a choice.
      </p>

      {confirming ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink">
            Delete <span className="data">{schemaName || "this schema"}</span>?
          </span>
          <Button
            type="button"
            variant="primary"
            disabled={deleting}
            onClick={() => void confirm()}
            className="border-error bg-error hover:border-error hover:bg-error/90"
          >
            {deleting ? "Deleting…" : "Yes, delete"}
          </Button>
          <Button type="button" disabled={deleting} onClick={() => setConfirming(false)}>
            Keep it
          </Button>
        </div>
      ) : (
        <Button type="button" className="mt-3" onClick={() => setConfirming(true)}>
          Delete schema
        </Button>
      )}
    </Panel>
  );
}
