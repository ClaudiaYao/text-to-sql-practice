import { useState } from "react";
import { AlertCircle, Sparkles, User } from "lucide-react";
import AnswerText from "./AnswerText";
import SqlPanel from "./SqlPanel";
import ResultsTable from "./ResultsTable";
import ResultsCards from "./ResultsCards";
import ViewToggle from "./ViewToggle";
import type { QueryResponse, ViewMode } from "../types";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end gap-2">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white whitespace-pre-wrap">
        {text}
      </div>
      <User className="w-5 h-5 mt-2 text-gray-300 shrink-0" />
    </div>
  );
}

export function AssistantBubble({ answer, error, result }: { answer: string; error: string | null; result: QueryResponse | null }) {
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  return (
    <div className="flex gap-2">
      <Sparkles className="w-5 h-5 mt-2 text-indigo-400 shrink-0" />
      <div className="min-w-0 flex-1 space-y-4">
        {error ? (
          <div className="flex gap-3 rounded-2xl border border-red-800 bg-red-950/40 p-4">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <pre className="text-xs text-red-300 whitespace-pre-wrap">{error}</pre>
          </div>
        ) : (
          <>
            <div className="rounded-2xl rounded-tl-sm bg-gray-900 border border-gray-800 px-4 py-2.5 text-sm text-gray-100">
              <AnswerText text={answer} />
            </div>
            {result && (
              <>
                <div className="flex gap-2 flex-wrap text-xs">
                  {result.cached && <span className="px-2 py-0.5 rounded-full bg-sky-900/50 border border-sky-700/50 text-sky-300">SQL cached</span>}
                  {result.truncated && <span className="px-2 py-0.5 rounded-full bg-amber-900/50 border border-amber-700/50 text-amber-300">Truncated</span>}
                  {result.agreement !== null && result.agreement < 1 && (
                    <span className="px-2 py-0.5 rounded-full bg-amber-900/50 border border-amber-700/50 text-amber-300">
                      Low agreement · {Math.round(result.agreement * 100)}%
                    </span>
                  )}
                  {result.standalone_question && (
                    <span className="text-gray-300 italic">Interpreted as: &ldquo;{result.standalone_question}&rdquo;</span>
                  )}
                </div>
                <SqlPanel sql={result.sql} executionMs={result.execution_ms} rowCount={result.row_count} attempts={result.attempts} />
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-200">
                    <span className="text-white font-semibold">{result.row_count.toLocaleString()}</span>{" "}
                    {result.row_count === 1 ? "row" : "rows"} (as stored when asked)
                  </p>
                  <ViewToggle mode={viewMode} onChange={setViewMode} />
                </div>
                {viewMode === "table" ? (
                  <ResultsTable columns={result.columns} rows={result.rows} />
                ) : (
                  <ResultsCards columns={result.columns} rows={result.rows} />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
