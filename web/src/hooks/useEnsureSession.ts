import { useEffect } from "react";
import { useSession } from "../context/SessionContext";

/**
 * Schemas are tenant data, so reading or writing them without a session is a
 * 401 — which renders as "Not authenticated", an alarming and wrong-headed
 * message for someone who just opened the app. The contract lets us mint an
 * anonymous trial, which is what the upload screen already does on arrival;
 * the schema screens take the same route so they are usable before signup.
 */
export function useEnsureSession(): {
  ready: boolean;
  loading: boolean;
  error: string | null;
  retry: () => void;
} {
  const { session, loading, error, ensureTrial } = useSession();

  useEffect(() => {
    if (session && !session.authenticated) void ensureTrial();
  }, [session, ensureTrial]);

  return {
    ready: session?.authenticated ?? false,
    loading,
    error,
    retry: () => void ensureTrial(),
  };
}
