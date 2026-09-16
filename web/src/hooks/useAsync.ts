import { useCallback, useEffect, useState } from "react";
import { describeError } from "../lib/api";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads once on mount (and whenever `deps` change) and always resolves into
 * one of three explicit states, so no screen can render a bare spinner or
 * swallow a rejection. Results from a stale run are discarded.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    load()
      .then((value) => {
        if (!live) return;
        setData(value);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setData(null);
        setError(describeError(cause));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, loading, reload };
}
