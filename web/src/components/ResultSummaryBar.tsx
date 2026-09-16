import type { ResultOut } from "../lib/types";

/** Dense instrumentation strip: the numbers the user checks before exporting. */
export function ResultSummaryBar({ result }: { result: ResultOut }) {
  const { summary } = result;
  const stats: Array<[string, string]> = [
    ["rows", String(summary.total_rows)],
    ["complete", `${summary.complete_rows}/${summary.total_rows}`],
    ["with warnings", String(summary.rows_with_warnings)],
    ["fields mapped", `${summary.mapped_fields.length}/${result.schema.fields.length}`],
    ["revision", String(result.revision)],
    ["provider", result.llm_provider],
    ["source", result.human_overridden ? "human override" : "model"],
  ];

  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4 lg:grid-cols-7">
      {stats.map(([label, value]) => (
        <div key={label} className="border-b border-line py-1">
          <dt className="text-[0.6875rem] text-info">{label}</dt>
          <dd className="data truncate text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
