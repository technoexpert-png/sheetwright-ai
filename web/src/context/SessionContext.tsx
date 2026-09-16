import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { auth, describeError } from "../lib/api";
import type { LoginBody, SessionOut, SignupBody } from "../lib/types";

interface SessionValue {
  session: SessionOut | null;
  /** Set when /auth/me itself failed (API down) — not when logged out. */
  error: string | null;
  loading: boolean;
  /** Creates an anonymous trial org if there is no session yet. */
  ensureTrial: () => Promise<void>;
  signup: (body: SignupBody) => Promise<void>;
  login: (body: LoginBody) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Guards against two components racing to create a trial org.
  const trialInFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSession(await auth.me());
      setError(null);
    } catch (cause) {
      setSession(null);
      setError(describeError(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const ensureTrial = useCallback(async () => {
    if (session?.authenticated) return;
    if (trialInFlight.current) return trialInFlight.current;
    const run = (async () => {
      try {
        setSession(await auth.trial());
        setError(null);
      } catch (cause) {
        // Silent by design: an upload can still create the session server-side,
        // so a failed trial call must not block the landing screen.
        setError(describeError(cause));
      } finally {
        trialInFlight.current = null;
      }
    })();
    trialInFlight.current = run;
    return run;
  }, [session?.authenticated]);

  const signup = useCallback(async (body: SignupBody) => {
    setSession(await auth.signup(body));
    setError(null);
  }, []);

  const login = useCallback(async (body: LoginBody) => {
    setSession(await auth.login(body));
    setError(null);
  }, []);

  const logout = useCallback(async () => {
    await auth.logout();
    await refresh();
  }, [refresh]);

  const value = useMemo<SessionValue>(
    () => ({ session, error, loading, ensureTrial, signup, login, logout, refresh }),
    [session, error, loading, ensureTrial, signup, login, logout, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}
