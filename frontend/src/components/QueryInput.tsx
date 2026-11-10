import { useState, useRef, type KeyboardEvent } from "react";
import { Send, Loader2, Database } from "lucide-react";

interface Props {
  onSubmit: (question: string) => void;
  loading: boolean;
}

const EXAMPLES = [
  "Show the top 10 customers by total payment amount",
  "Which films were rented the most times?",
  "List all actors who appeared in more than 30 films",
  "What are the total sales per store?",
  "Find all customers who have never returned a rental",
];

export default function QueryInput({ onSubmit, loading }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const q = value.trim();
    if (!q || loading) return;
    onSubmit(q);
    setValue("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="w-full space-y-4">
      {/* Input box */}
      <div className="relative bg-gray-900 border border-gray-700 rounded-2xl shadow-xl focus-within:border-indigo-500 transition-colors">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask anything about the Sakila DVD-rental database…"
          rows={2}
          disabled={loading}
          className="w-full bg-transparent text-gray-100 placeholder-gray-400 resize-none p-5 pr-16 text-base outline-none rounded-2xl"
        />
        <button
          onClick={submit}
          disabled={loading || !value.trim()}
          className="absolute bottom-4 right-4 flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Example chips */}
      <div className="flex flex-wrap gap-2">
        <span className="flex items-center gap-1 text-xs text-gray-300 mr-1">
          <Database className="w-3 h-3" /> Try:
        </span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => { setValue(ex); textareaRef.current?.focus(); }}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-full bg-gray-800 hover:bg-gray-700 text-gray-100 border border-gray-700 hover:border-gray-600 transition-colors disabled:opacity-40"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
