import { useState } from "react";
import { AlertCircle, Sparkles } from "lucide-react";
import QueryInput from "./components/QueryInput";
import SqlPanel from "./components/SqlPanel";
import ResultsTable from "./components/ResultsTable";
import ResultsCards from "./components/ResultsCards";
import ViewToggle from "./components/ViewToggle";
import { runQuery } from "./api";
import type { QueryResponse, ViewMode } from "./types";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [lastQuestion, setLastQuestion] = useState("");

  const handleQuery = async (question: string) => {
    setLoading(true);
    setError(null);
    setLastQuestion(question);
    try {
      const data = await runQuery(question);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-600">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white leading-none">SQL Copilot</h1>
            <p className="text-xs text-gray-300 leading-none mt-0.5">Sakila DVD-rental · PostgreSQL</p>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-6 py-10 space-y-8">
        {/* Hero */}
        {!result && !loading && !error && (
          <div className="text-center py-8 space-y-3">
            <h2 className="text-4xl font-bold text-white tracking-tight">
              Ask your database anything
            </h2>
            <p className="text-gray-200 text-lg">
              Type a question in plain English — the AI translates it to SQL and runs it instantly.
            </p>
          </div>
        )}

        {/* Query input */}
        <QueryInput onSubmit={handleQuery} loading={loading} />

        {/* Error banner */}
        {error && (
          <div className="flex gap-3 rounded-2xl border border-red-800 bg-red-950/40 p-5">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-red-300 mb-1">Query failed</p>
              <pre className="text-xs text-red-400 whitespace-pre-wrap">{error}</pre>
            </div>
          </div>
        )}

        {/* Skeleton while loading */}
        {loading && (
          <div className="space-y-4 animate-pulse">
            <div className="h-24 rounded-2xl bg-gray-800" />
            <div className="h-64 rounded-2xl bg-gray-800" />
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div className="space-y-5">
            {/* Question recap */}
            <div className="flex items-center gap-2 text-sm text-gray-200">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span className="italic">&ldquo;{lastQuestion}&rdquo;</span>
            </div>

            {/* SQL panel */}
            <SqlPanel
              sql={result.sql}
              executionMs={result.execution_ms}
              rowCount={result.row_count}
              attempts={result.attempts}
            />

            {/* Results header */}
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-200">
                <span className="text-white font-semibold">{result.row_count.toLocaleString()}</span>{" "}
                {result.row_count === 1 ? "row" : "rows"} returned
              </p>
              <ViewToggle mode={viewMode} onChange={setViewMode} />
            </div>

            {/* Data */}
            {viewMode === "table" ? (
              <ResultsTable columns={result.columns} rows={result.rows} />
            ) : (
              <ResultsCards columns={result.columns} rows={result.rows} />
            )}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-4 text-center text-xs text-gray-400">
        SQL Copilot · Powered by AWS Bedrock · Sakila sample database
      </footer>
    </div>
  );
}
