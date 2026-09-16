import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Panel } from "./Panel";

interface Props {
  title: string;
  intro: ReactNode;
  footer: ReactNode;
  children: ReactNode;
}

/** Narrow single-column frame shared by /login and /signup. */
export function AuthShell({ title, intro, footer, children }: Props) {
  return (
    <div className="mx-auto max-w-md space-y-3">
      <Panel title={title} description={intro}>
        {children}
      </Panel>
      <p className="text-center text-xs text-info">{footer}</p>
      <p className="text-center text-xs">
        <Link to="/" className="text-accent underline">
          Back to upload
        </Link>
      </p>
    </div>
  );
}
