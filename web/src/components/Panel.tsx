import type { ReactNode } from "react";

interface Props {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  bodyClassName?: string;
}

/** White card on the paper ground; structure comes from borders, not shadow. */
export function Panel({
  title,
  description,
  actions,
  children,
  bodyClassName = "p-4",
}: Props) {
  return (
    <section className="rounded-md border border-line bg-white">
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-info">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
