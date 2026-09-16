import { Link } from "react-router-dom";
import { Panel } from "../components/Panel";

export function NotFoundPage() {
  return (
    <Panel title="Not found">
      <p className="text-sm text-info">That page does not exist.</p>
      <Link to="/" className="mt-2 inline-block text-xs text-accent underline">
        Back to upload
      </Link>
    </Panel>
  );
}
