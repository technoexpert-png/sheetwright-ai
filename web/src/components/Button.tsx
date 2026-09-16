import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "quiet";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

// Sharp 6px corners and hairline borders, never pills. The rust accent is
// reserved for primary actions so it stays meaningful.
const VARIANTS: Record<Variant, string> = {
  primary:
    "border-accent bg-accent text-white hover:border-accent-strong hover:bg-accent-strong",
  secondary: "border-line-strong bg-white text-ink hover:border-ink/40 hover:bg-paper",
  quiet: "border-transparent bg-transparent text-info hover:border-line hover:text-ink",
};

export function Button({ variant = "secondary", className = "", ...rest }: Props) {
  return (
    <button
      {...rest}
      className={[
        "inline-flex items-center justify-center gap-2 rounded-md border px-3 py-1.5",
        "text-sm font-medium transition-colors",
        // Disabled buttons drop their variant colour entirely rather than
        // fading it, so a greyed-out primary never reads as a pale accent.
        "disabled:cursor-not-allowed disabled:border-line disabled:bg-paper disabled:text-info/60",
        VARIANTS[variant],
        className,
      ].join(" ")}
    />
  );
}
