import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { usePolledUpload } from "../hooks/usePolledUpload";
import { Panel } from "../components/Panel";
import { Button } from "../components/Button";
import { ErrorState, LoadingState } from "../components/StateBlocks";
import { StatusBadge } from "../components/StatusBadge";
import { formatBytes, formatStage } from "../lib/format";

export function ProcessingPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { upload, error, loading } = usePolledUpload(id);

  // Finished work belongs on the review screen; `replace` keeps Back going to
  // the upload form rather than bouncing through this transient page.
  useEffect(() => {
    if (!upload) return;
    if (upload.status === "needs_review" || upload.status === "complete") {
      navigate(`/u/${upload.id}/review`, { replace: true });
    }
  }, [upload, navigate]);

  if (loading) {
    return (
      <Panel title="Processing">
        <LoadingState label="Fetching upload status…" />
      </Panel>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <ErrorState title="Lost contact with this upload" message={error} />
        <Link to="/uploads" className="inline-block text-xs text-accent underline">
          Back to history
        </Link>
      </div>
    );
  }

  if (!upload) return null;

  if (upload.status === "error") {
    return (
      <Panel title="Mapping failed" description={upload.filename}>
        <div className="space-y-3">
          <p className="rounded-md border border-error/30 bg-error-wash px-3 py-2 text-sm text-ink">
            {upload.error ?? "The mapping run failed without a message."}
          </p>
          {upload.required_action && (
            <div>
              <p className="text-xs font-semibold text-ink">What to do</p>
              <p className="mt-0.5 text-sm text-info">{upload.required_action}</p>
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => navigate("/")}>
              Upload a corrected file
            </Button>
            <Button onClick={() => navigate("/uploads")}>View history</Button>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Mapping in progress" description={upload.filename}>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <StatusBadge status={upload.status} />
          <span
            aria-hidden="true"
            className="size-3 animate-spin rounded-md border border-line-strong border-t-accent"
          />
          {/* Screen readers get the stage changes as they happen. */}
          <p aria-live="polite" className="data text-ink">
            {formatStage(upload.stage)}
          </p>
        </div>

        <dl className="grid max-w-3xl gap-x-8 gap-y-1.5 sm:grid-cols-2">
          {[
            ["File", upload.filename],
            ["Size", formatBytes(upload.size_bytes)],
            ["Rows found", upload.row_count === null ? "counting…" : String(upload.row_count)],
            ["Upload id", upload.id],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 border-b border-line py-1">
              <dt className="text-xs text-info">{label}</dt>
              <dd className="data truncate text-ink">{value}</dd>
            </div>
          ))}
        </dl>

        <p className="text-xs text-info">
          Status refreshes every second. You will be taken to the review step automatically.
        </p>
      </div>
    </Panel>
  );
}
