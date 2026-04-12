interface Props {
  columns: string[];
  rows: unknown[][];
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Detect the "best" field to use as a card title: prefer name/title/id columns */
function pickTitle(columns: string[]): number {
  const priority = ["title", "name", "full_name", "first_name", "film_title", "customer"];
  for (const p of priority) {
    const idx = columns.findIndex((c) => c.toLowerCase().includes(p));
    if (idx !== -1) return idx;
  }
  return 0;
}

export default function ResultsCards({ columns, rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="text-center py-16 text-gray-500 text-sm">
        Query returned no rows.
      </div>
    );
  }

  const titleIdx = pickTitle(columns);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {rows.map((row, ri) => (
        <div
          key={ri}
          className="rounded-2xl border border-gray-800 bg-gray-900 p-5 hover:border-indigo-700 hover:bg-gray-800/70 transition-all"
        >
          <p className="text-base font-semibold text-indigo-300 mb-3 truncate">
            {cell(row[titleIdx])}
          </p>
          <dl className="space-y-1.5">
            {columns.map((col, ci) => {
              if (ci === titleIdx) return null;
              return (
                <div key={col} className="flex justify-between gap-4 text-xs">
                  <dt className="text-gray-500 uppercase tracking-wide shrink-0">{col}</dt>
                  <dd className="text-gray-300 text-right truncate max-w-[160px]">
                    {cell(row[ci])}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      ))}
    </div>
  );
}
