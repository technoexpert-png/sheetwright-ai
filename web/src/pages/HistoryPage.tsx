import { useNavigate } from "react-router-dom";
import { uploads } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { Panel } from "../components/Panel";
import { Button } from "../components/Button";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../lib/format";
import type { UploadOut } from "../lib/types";

const COLUMNS = ["File", "Schema", "Status", "Rows", "Flags", "Created", ""];

function destination(upload: UploadOut): string {
  // A finished upload goes straight to its review; anything else to the
  // processing screen, which redirects once it settles.
  return upload.status === "needs_review" || upload.status === "complete"
    ? `/u/${upload.id}/review`
    : `/u/${upload.id}`;
}

function flagText(upload: UploadOut): string {
  const { error, warning, info } = upload.diagnostic_counts;
  const parts = [
    error ? `${error}E` : null,
    warning ? `${warning}W` : null,
    info ? `${info}I` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" ") : "—";
}

export function HistoryPage() {
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(() => uploads.list(), []);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-ink">Uploads</h1>

      <Panel bodyClassName="p-0">
        {loading && (
          <div className="px-4">
            <LoadingState label="Loading your uploads…" />
          </div>
        )}

        {error && (
          <div className="p-4">
            <ErrorState title="Could not load uploads" message={error} onRetry={reload} />
          </div>
        )}

        {data && data.length === 0 && (
          <div className="p-4">
            <EmptyState title="Nothing uploaded yet">
              Start from the upload screen and your runs will be listed here.
            </EmptyState>
          </div>
        )}

        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line-strong">
                  {COLUMNS.map((column, index) => (
                    <th
                      key={column || index}
                      scope="col"
                      className="px-4 py-2 text-xs font-semibold text-info"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((upload) => (
                  <tr key={upload.id} className="border-b border-line hover:bg-paper">
                    <td className="data max-w-72 truncate px-4 py-2 text-ink">
                      {upload.filename}
                    </td>
                    <td className="data px-4 py-2 text-info">{upload.schema_id}</td>
                    <td className="px-4 py-2">
                      <StatusBadge status={upload.status} />
                    </td>
                    <td className="data px-4 py-2 text-ink">{upload.row_count ?? "—"}</td>
                    <td className="data px-4 py-2 text-info">{flagText(upload)}</td>
                    <td className="data px-4 py-2 whitespace-nowrap text-info">
                      {formatDateTime(upload.created_at)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {/* A real button, not a clickable row: keyboard reachable
                          and announced as the action it performs. */}
                      <Button variant="quiet" onClick={() => navigate(destination(upload))}>
                        Open
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
