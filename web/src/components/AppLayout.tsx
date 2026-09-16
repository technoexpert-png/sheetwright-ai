import { Outlet } from "react-router-dom";
import { AppHeader } from "./AppHeader";
import { useSession } from "../context/SessionContext";

export function AppLayout() {
  const { error } = useSession();

  return (
    <div className="min-h-dvh bg-paper">
      <AppHeader />
      {/* Session lookup failing means the API is unreachable; say so once, at
          the top, rather than letting every screen guess. */}
      {error && (
        <p
          role="status"
          className="border-b border-warning/30 bg-warning-wash px-5 py-2 text-center text-xs text-warning"
        >
          {error}
        </p>
      )}
      <main className="mx-auto w-full max-w-[1180px] px-5 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-[1180px] px-5 pb-8 text-xs text-info">
        Sheetwright maps spreadsheets onto your schema and shows you every decision it made.
      </footer>
    </div>
  );
}
