import { Link } from "react-router-dom";
import { Panel } from "./Panel";
import { Button } from "./Button";
import type { UploadStatus } from "../lib/types";

/**
 * The two "the result exists but you cannot have it" answers from
 * `/uploads/{id}/result`: 409 (still processing) and 422 (the run failed).
 */
export function StillProcessingPanel({
  status,
  onWatch,
}: {
  status: UploadStatus;
  onWatch: () => void;
}) {
  return (
    <Panel title="Still working">
      <p className="text-sm text-info">
        This upload is <span className="data text-ink">{status}</span>; the result is not ready
        yet.
      </p>
      <Button className="mt-3" variant="primary" onClick={onWatch}>
        Watch progress
      </Button>
    </Panel>
  );
}

export function FailedUploadPanel({
  error,
  requiredAction,
}: {
  error: string | null;
  requiredAction: string | null;
}) {
  return (
    <Panel title="This upload failed">
      <p className="text-sm text-ink">{error ?? "No error message was returned."}</p>
      {requiredAction && <p className="mt-2 text-sm text-info">{requiredAction}</p>}
      <Link to="/" className="mt-3 inline-block text-xs text-accent underline">
        Upload a corrected file
      </Link>
    </Panel>
  );
}
