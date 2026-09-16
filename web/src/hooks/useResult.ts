import { useCallback, useEffect, useState } from "react";
import {
  conflictStatus as readConflictStatus,
  describeError,
  failureDetail,
  uploads,
} from "../lib/api";
import type { ResultOut, UploadStatus } from "../lib/types";

export interface ResultState {
  result: ResultOut | null;
  /** Generic error text; null when the failure was a 409/422 we can explain. */
  error: string | null;
  /** Set on 409 — "valid request, wrong time"; carries the live status. */
  stillProcessing: UploadStatus | null;
  /** Set on 422 — the upload failed. */
  failure: { error: string | null; required_action: string | null } | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads `/uploads/{id}/result`, translating the contract's two special
 * responses (409 still processing, 422 failed upload) into states the review
 * screen can render instead of a generic error.
 */
export function useResult(
  id: string | undefined,
  page: { limit: number; offset: number },
): ResultState {
  const [result, setResult] = useState<ResultOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stillProcessing, setStillProcessing] = useState<UploadStatus | null>(null);
  const [failure, setFailure] = useState<ResultState["failure"]>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!id) return;
    let live = true;
    setLoading(true);
    setError(null);
    setStillProcessing(null);
    setFailure(null);

    uploads
      .result(id, page)
      .then((value) => {
        if (live) setResult(value);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setResult(null);
        const conflict = readConflictStatus(cause);
        const failed = failureDetail(cause);
        if (conflict) setStillProcessing(conflict);
        else if (failed) setFailure(failed);
        else setError(describeError(cause));
      })
      .finally(() => {
        if (live) setLoading(false);
      });

    return () => {
      live = false;
    };
    // `page` is a fresh object on every render, so depend on its values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, page.limit, page.offset, nonce]);

  return { result, error, stillProcessing, failure, loading, reload };
}
