import type { ReactNode } from "react";
import { Button } from "./Button";

/** Never a bare spinner: a loading state always names what it is waiting for. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-6 text-sm text-info" aria-busy="true">
      <span
        aria-hidden="true"
        className="size-3 shrink-0 animate-spin rounded-md border border-line-strong border-t-accent"
      />
      <span>{label}</span>
    </div>
  );
}

interface ErrorProps {
  title?: string;
  message: string;
  hint?: ReactNode;
  onRetry?: () => void;
}

export function ErrorState({ title = "Something went wrong", message, hint, onRetry }: ErrorProps) {
  return (
    <div
      role="alert"
      className="rounded-md border border-error/30 bg-error-wash px-4 py-3 text-sm"
    >
      <p className="font-semibold text-error">{title}</p>
      <p className="mt-1 text-ink">{message}</p>
      {hint && <p className="mt-1 text-xs text-info">{hint}</p>}
      {onRetry && (
        <Button className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-xs text-info">{children}</div>}
    </div>
  );
}
