interface Props {
  columns: string[];
  rows: unknown[][];
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ResultsTable({ columns, rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="text-center py-16 text-gray-500 text-sm">
        Query returned no rows.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-900 border-b border-gray-800">
            {columns.map((col) => (
              <th
                key={col}
                className="px-4 py-3 text-left font-semibold text-indigo-300 whitespace-nowrap uppercase tracking-wide text-xs"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className={`border-b border-gray-800/60 transition-colors hover:bg-gray-800/50 ${
                ri % 2 === 0 ? "bg-gray-950" : "bg-gray-900/40"
              }`}
            >
              {row.map((val, ci) => (
                <td key={ci} className="px-4 py-2.5 text-gray-300 whitespace-nowrap">
                  {cell(val)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
