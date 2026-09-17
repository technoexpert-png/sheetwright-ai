import type { ReactNode } from "react";
import { useEnsureSession } from "../hooks/useEnsureSession";
import { ErrorState, LoadingState } from "./StateBlocks";

/**
 * Holds a screen back until a session exists (minting an anonymous trial if
 * needed), so the screens below never have to thread "is there a session yet"
 * through their own loading states — they simply mount when they can fetch.
 */
export function SessionGate({ children }: { children: ReactNode }) {
  const { ready, loading, error, retry } = useEnsureSession();

  if (error) {
    return <ErrorState title="Could not start a session" message={error} onRetry={retry} />;
  }
  if (!ready) {
    return (
      <LoadingState label={loading ? "Checking your session…" : "Preparing your workspace…"} />
    );
  }
  return <>{children}</>;
}
