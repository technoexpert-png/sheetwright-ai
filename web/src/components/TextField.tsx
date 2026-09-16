import { useId, type InputHTMLAttributes } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

export function TextField({ label, hint, className = "", ...rest }: Props) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-semibold text-ink">
        {label}
      </label>
      <input
        {...rest}
        id={id}
        aria-describedby={hintId}
        className={`data mt-1.5 w-full rounded-md border border-line-strong bg-white px-2 py-1.5 text-ink ${className}`}
      />
      {hint && (
        <p id={hintId} className="mt-1 text-[0.6875rem] text-info">
          {hint}
        </p>
      )}
    </div>
  );
}
