import { useEffect, useRef, useState } from "react";
import { describeError, uploads } from "../lib/api";
import type { UploadOut } from "../lib/types";

/**
 * 1s cadence: mapping runs finish in seconds, so anything slower makes the
 * processing screen feel stalled, and the endpoint is a cheap status read.
 * Polling stops as soon as the upload reaches a terminal status, so a finished
 * job costs nothing.
 */
const POLL_MS = 1000;

const TERMINAL = new Set<UploadOut["status"]>(["needs_review", "complete", "error"]);

export interface PolledUpload {
  upload: UploadOut | null;
  error: string | null;
  loading: boolean;
  /** True while the status is still pending/running. */
  polling: boolean;
}

export function usePolledUpload(id: string | undefined): PolledUpload {
  const [upload, setUpload] = useState<UploadOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!id) {
      setError("No upload id in the URL.");
      setLoading(false);
      return;
    }

    let live = true;
    setLoading(true);
    setError(null);
    setUpload(null);

    const tick = async () => {
      try {
        const next = await uploads.get(id);
        if (!live) return;
        setUpload(next);
        setError(null);
        setLoading(false);
        if (!TERMINAL.has(next.status)) {
          timer.current = window.setTimeout(tick, POLL_MS);
        }
      } catch (cause) {
        if (!live) return;
        // A failed poll is terminal for the UI: keep retrying silently and the
        // user stares at a frozen screen with no explanation.
        setError(describeError(cause));
        setLoading(false);
      }
    };

    void tick();

    return () => {
      live = false;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
    };
  }, [id]);

  return {
    upload,
    error,
    loading,
    polling: Boolean(upload && !TERMINAL.has(upload.status)),
  };
}
