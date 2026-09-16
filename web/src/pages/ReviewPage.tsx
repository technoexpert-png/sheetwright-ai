import { useCallback, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { describeError, uploads } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { useResult } from "../hooks/useResult";
import { useMappingDraft } from "../hooks/useMappingDraft";
import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import { ErrorState, LoadingState } from "../components/StateBlocks";
import { StatusBadge } from "../components/StatusBadge";
import { MappingTable } from "../components/MappingTable";
import { UnmappedColumns } from "../components/UnmappedColumns";
import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import { PreviewTable } from "../components/PreviewTable";
import { ResultSummaryBar } from "../components/ResultSummaryBar";
import { ExportButtons } from "../components/ExportButtons";
import { RowPager } from "../components/RowPager";
import {
  FailedUploadPanel,
  StillProcessingPanel,
} from "../components/ReviewUnavailable";

const PAGE_SIZE = 100; // Matches the contract's default `limit`.

export function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const upload = useAsync(
    () => (id ? uploads.get(id) : Promise.reject(new Error("Missing upload id."))),
    [id],
  );
  const { result, error, stillProcessing, failure, loading, reload } = useResult(id, {
    limit: PAGE_SIZE,
    offset,
  });
  const mapping = useMappingDraft(result);

  const [focusedRow, setFocusedRow] = useState<number | null>(null);
  const [rowNotice, setRowNotice] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  const registerRow = useCallback((row: number, element: HTMLTableRowElement | null) => {
    if (element) rowRefs.current.set(row, element);
    else rowRefs.current.delete(row);
  }, []);

  // Diagnostics reference absolute source rows, which may sit outside the
  // loaded page — say so rather than silently doing nothing.
  const focusRow = useCallback((row: number) => {
    setFocusedRow(row);
    const element = rowRefs.current.get(row);
    if (element) {
      element.scrollIntoView({ block: "center", behavior: "smooth" });
      setRowNotice(null);
    } else {
      setRowNotice(`Row ${row} is not on this page of the preview.`);
    }
  }, []);

  async function rerun() {
    if (!id) return;
    setRerunning(true);
    setRerunError(null);
    try {
      await uploads.overrideMapping(id, mapping.payload);
      navigate(`/u/${id}`);
    } catch (cause) {
      setRerunError(describeError(cause));
      setRerunning(false);
    }
  }

  if (loading) return <LoadingState label="Loading the proposed mapping…" />;

  if (stillProcessing) {
    return (
      <StillProcessingPanel status={stillProcessing} onWatch={() => navigate(`/u/${id}`)} />
    );
  }

  if (failure) {
    return (
      <FailedUploadPanel error={failure.error} requiredAction={failure.required_action} />
    );
  }

  if (error) return <ErrorState title="Could not load the result" message={error} onRetry={reload} />;
  if (!result) return null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-ink">
          {upload.data?.filename ?? "Review mapping"}
        </h1>
        {upload.data && <StatusBadge status={upload.data.status} />}
        <span className="data text-info">→ {result.schema.name}</span>
      </div>

      <Panel bodyClassName="px-4 py-3">
        <ResultSummaryBar result={result} />
      </Panel>

      <Panel
        title="Column mapping"
        description="Ambiguous and unmet required fields are listed first. Override anything, then re-run."
        actions={
          <>
            <span className="data text-xs text-info">
              {mapping.changedFields.length} edited
            </span>
            <Button onClick={mapping.reset} disabled={mapping.changedFields.length === 0}>
              Reset
            </Button>
            <Button variant="primary" onClick={() => void rerun()} disabled={rerunning}>
              {rerunning ? "Re-running…" : "Re-run with these mappings"}
            </Button>
          </>
        }
        bodyClassName="p-0"
      >
        {rerunError && (
          <div className="px-4 pt-4">
            <ErrorState title="Re-run failed" message={rerunError} />
          </div>
        )}
        <MappingTable result={result} draft={mapping.draft} onSelect={mapping.set} />
        <div className="border-t border-line px-4 py-3">
          <p className="mb-1.5 text-xs font-semibold text-ink">Unused source columns</p>
          <UnmappedColumns columns={result.unmapped_source_columns} />
        </div>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Panel title="Diagnostics" description="Click a row number to jump to it.">
          <DiagnosticsPanel diagnostics={result.diagnostics} onFocusRow={focusRow} />
        </Panel>

        <Panel
          title="Data preview"
          description="Mapped output, with the original row number."
          actions={<ExportButtons uploadId={result.upload_id} filename={upload.data?.filename ?? "export"} />}
          bodyClassName="p-0"
        >
          {rowNotice && (
            <p role="status" className="border-b border-line bg-warning-wash px-4 py-2 text-xs text-warning">
              {rowNotice}
            </p>
          )}
          <PreviewTable result={result} focusedRow={focusedRow} registerRow={registerRow} />
          <RowPager
            offset={offset}
            limit={PAGE_SIZE}
            loaded={result.rows.length}
            total={result.summary.total_rows}
            onChange={setOffset}
          />
        </Panel>
      </div>
    </div>
  );
}
