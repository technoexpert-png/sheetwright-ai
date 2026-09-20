import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { describeError } from "../lib/api";
import { AuthShell } from "../components/AuthShell";
import { TextField } from "../components/TextField";
import { Button } from "../components/Button";
import { ErrorState } from "../components/StateBlocks";

export function SignupPage() {
  const { session, signup } = useSession();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fromTrial = Boolean(session?.org?.is_trial);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signup({ org_name: orgName, email, password });
      navigate("/uploads");
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Create an account"
      intro={
        fromTrial
          ? "Your trial workspace becomes this account — the uploads and mappings you have already made are kept."
          : "One account per organization; you can invite colleagues later."
      }
      footer={
        <>
          Already have one?{" "}
          <Link to="/login" className="text-accent underline">
            Log in
          </Link>
          .
        </>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        <TextField
          label="Organization name"
          value={orgName}
          autoComplete="organization"
          required
          onChange={(event) => setOrgName(event.target.value)}
        />
        <TextField
          label="Work email"
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
          autoComplete="new-password"
          required
          minLength={8}
          hint="At least 8 characters."
          onChange={(event) => setPassword(event.target.value)}
        />
        {error && <ErrorState title="Could not sign up" message={error} />}
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  );
}
