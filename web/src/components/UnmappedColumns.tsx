interface Props {
  columns: string[];
}

/**
 * Columns present in the file that no schema field claimed. Shown because a
 * leftover column is usually the clue that a mapping is wrong.
 */
export function UnmappedColumns({ columns }: Props) {
  if (columns.length === 0) {
    return <p className="text-xs text-info">Every source column was used.</p>;
  }

  return (
    <ul className="flex flex-wrap gap-1.5">
      {columns.map((column) => (
        <li
          key={column}
          className="data rounded-md border border-line bg-paper px-1.5 py-0.5 text-info"
        >
          {column}
        </li>
      ))}
    </ul>
  );
}
