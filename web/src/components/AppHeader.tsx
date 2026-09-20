import { NavLink, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { Button } from "./Button";

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "rounded-md border px-2.5 py-1 text-sm transition-colors",
    isActive
      ? "border-accent/40 bg-accent-wash text-accent-strong"
      : "border-transparent text-info hover:border-line hover:text-ink",
  ].join(" ");
}

export function AppHeader() {
  const { session, logout } = useSession();
  const navigate = useNavigate();
  const org = session?.org ?? null;
  const signedIn = Boolean(session?.authenticated && !session.anonymous);

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-2.5">
        <NavLink to="/" className="flex items-baseline gap-1.5">
          <span className="text-[0.95rem] font-semibold text-ink">Sheetwright</span>
          <span className="data text-[0.6875rem] text-accent">AI</span>
        </NavLink>

        <nav className="flex items-center gap-1" aria-label="Main">
          <NavLink to="/" end className={navClass}>
            Upload
          </NavLink>
          <NavLink to="/schemas" className={navClass}>
            Schemas
          </NavLink>
          <NavLink to="/uploads" className={navClass}>
            History
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {/* A trial org's name is a placeholder ("Trial"), so showing it in the
              header is noise rather than information — the trial notice on the
              upload screen already says what matters. A real organization's
              name is worth showing, because it tells you which tenant you are
              acting in. */}
          {org && !org.is_trial && (
            <span className="data text-ink">{org.name}</span>
          )}
          {signedIn ? (
            <Button variant="quiet" onClick={() => void logout()}>
              Log out
            </Button>
          ) : (
            <>
              <Button variant="quiet" onClick={() => navigate("/login")}>
                Log in
              </Button>
              <Button variant="primary" onClick={() => navigate("/signup")}>
                Sign up
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
