import { useState } from "react";
import { ChevronDown, ChevronUp, Copy, Check, Code2, RefreshCw } from "lucide-react";

interface Props {
  sql: string;
  executionMs: number;
  rowCount: number;
  attempts: number;
}

export default function SqlPanel({ sql, executionMs, rowCount, attempts }: Props) {
  const [open, setOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3 cursor-pointer hover:bg-gray-800/50 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex items-center gap-2 flex-wrap">
          <Code2 className="w-4 h-4 text-indigo-400 shrink-0" />
          <span className="text-sm font-semibold text-gray-200">Generated SQL</span>
          <span className="text-xs text-gray-500">
            {rowCount.toLocaleString()} rows &middot; {executionMs} ms
          </span>
          {attempts > 1 && (
            <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-900/50 border border-amber-700/50 text-amber-300">
              <RefreshCw className="w-3 h-3" />
              Self-corrected &middot; {attempts} attempts
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); copy(); }}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
          >
            {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
            {copied ? "Copied!" : "Copy"}
          </button>
          {open ? (
            <ChevronUp className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          )}
        </div>
      </div>

      {/* Code block */}
      {open && (
        <div className="border-t border-gray-800">
          <pre className="overflow-x-auto p-5 text-sm text-emerald-300 font-mono leading-relaxed whitespace-pre-wrap">
            {sql}
          </pre>
        </div>
      )}
    </div>
  );
}
