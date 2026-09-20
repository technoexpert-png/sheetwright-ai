import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { describeError } from "../lib/api";
import { AuthShell } from "../components/AuthShell";
import { TextField } from "../components/TextField";
import { Button } from "../components/Button";
import { ErrorState } from "../components/StateBlocks";

export function LoginPage() {
  const { login } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgId, setOrgId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // `org_id` is optional in the contract; send it only when given.
      await login({ email, password, ...(orgId ? { org_id: orgId } : {}) });
      navigate("/uploads");
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Log in"
      intro="Pick up your uploads and the mappings you saved."
      footer={
        <>
          No account?{" "}
          <Link to="/signup" className="text-accent underline">
            Sign up
          </Link>{" "}
          — a trial workspace keeps its work.
        </>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        <TextField
          label="Email"
          type="email"
          value={email}
          autoComplete="email"
          required
          onChange={(event) => setEmail(event.target.value)}
        />
        <TextField
          label="Password"
          type="password"
          value={password}
          autoComplete="current-password"
          required
          onChange={(event) => setPassword(event.target.value)}
        />
        <TextField
          label="Organization id (optional)"
          value={orgId}
          hint="Only needed if your email belongs to more than one organization."
          onChange={(event) => setOrgId(event.target.value)}
        />
        {error && <ErrorState title="Could not log in" message={error} />}
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </AuthShell>
  );
}
