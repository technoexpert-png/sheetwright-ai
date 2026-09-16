import { Button } from "./Button";

interface Props {
  offset: number;
  limit: number;
  loaded: number;
  total: number;
  onChange: (offset: number) => void;
}

/** `/result` pages its `rows` but not its `summary`, so paging is preview-only. */
export function RowPager({ offset, limit, loaded, total, onChange }: Props) {
  const first = total === 0 ? 0 : offset + 1;
  const last = offset + loaded;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
      <p className="data text-xs text-info">
        rows {first}–{last} of {total}
      </p>
      <div className="flex gap-2">
        <Button disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button disabled={last >= total} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </div>
  );
}
