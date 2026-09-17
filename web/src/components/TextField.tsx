import { useId, type InputHTMLAttributes } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  /** Inline validation message, announced and bound via aria-describedby. */
  error?: string | null;
}

export function TextField({ label, hint, error, className = "", ...rest }: Props) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-semibold text-ink">
        {label}
      </label>
      <input
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={[errorId, hintId].filter(Boolean).join(" ") || undefined}
        className={`data mt-1.5 w-full rounded-md border bg-white px-2 py-1.5 text-ink ${
          error ? "border-error" : "border-line-strong"
        } ${className}`}
      />
      {error && (
        <p id={errorId} role="alert" className="mt-1 text-[0.6875rem] text-error">
          {error}
        </p>
      )}
      {hint && (
        <p id={hintId} className="mt-1 text-[0.6875rem] text-info">
          {hint}
        </p>
      )}
    </div>
  );
}
