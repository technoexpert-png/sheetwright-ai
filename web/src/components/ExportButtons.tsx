import { useState } from "react";
import { describeError, saveBlob, uploads } from "../lib/api";
import type { ExportFormat } from "../lib/types";
import { Button } from "./Button";

const FORMATS: ExportFormat[] = ["csv", "xlsx", "json"];

interface Props {
  uploadId: string;
  /** Original filename, used to name the download. */
  filename: string;
}

export function ExportButtons({ uploadId, filename }: Props) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(format: ExportFormat) {
    setBusy(format);
    setError(null);
    try {
      const blob = await uploads.exportFile(uploadId, format);
      const base = filename.replace(/\.[^.]+$/, "") || "sheetwright";
      saveBlob(blob, `${base}.mapped.${format}`);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {FORMATS.map((format) => (
        <Button
          key={format}
          disabled={busy !== null}
          onClick={() => void download(format)}
          className="data"
        >
          {busy === format ? `${format}…` : format}
        </Button>
      ))}
      {error && (
        <span role="alert" className="text-xs text-error">
          {error}
        </span>
      )}
    </div>
  );
}
