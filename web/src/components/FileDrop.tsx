import { useId, useRef, useState } from "react";
import { formatBytes } from "../lib/format";

const ACCEPTED = [".csv", ".xlsx"];

function isAccepted(file: File): boolean {
  return ACCEPTED.some((extension) => file.name.toLowerCase().endsWith(extension));
}

interface Props {
  file: File | null;
  onSelect: (file: File | null) => void;
  disabled?: boolean;
}

export function FileDrop({ file, onSelect, disabled }: Props) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    if (!isAccepted(candidate)) {
      setRejected(`${candidate.name} is not a .csv or .xlsx file.`);
      return;
    }
    setRejected(null);
    onSelect(candidate);
  }

  return (
    <div>
      <label htmlFor={inputId} className="block text-xs font-semibold text-ink">
        Spreadsheet
      </label>

      {/* The label is the drop target and the click target, so the native file
          input stays the single accessible control (keyboard + screen reader). */}
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!disabled) accept(event.dataTransfer.files[0]);
        }}
        className={[
          "mt-1.5 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed px-4 py-8 text-center transition-colors",
          dragging ? "border-accent bg-accent-wash" : "border-line-strong bg-paper",
          disabled ? "pointer-events-none opacity-50" : "hover:border-ink/30",
        ].join(" ")}
      >
        <span className="text-sm text-ink">
          Drag a file here, or <span className="text-accent underline">browse</span>
        </span>
        <span className="data text-[0.6875rem] text-info">.csv or .xlsx</span>
      </label>

      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        disabled={disabled}
        className="sr-only"
        onChange={(event) => accept(event.target.files?.[0])}
      />

      {file && (
        <p className="data mt-2 flex items-center gap-2 text-ink">
          <span>{file.name}</span>
          <span className="text-info">{formatBytes(file.size)}</span>
          <button
            type="button"
            className="rounded-md border border-line px-1.5 text-[0.6875rem] text-info hover:border-ink/40 hover:text-ink"
            onClick={() => {
              onSelect(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            clear
          </button>
        </p>
      )}

      {rejected && (
        <p role="alert" className="mt-2 text-xs text-error">
          {rejected}
        </p>
      )}
    </div>
  );
}
