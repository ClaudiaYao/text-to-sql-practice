import { MessageSquare, Plus, Trash2 } from "lucide-react";
import type { ConversationSummary } from "../types";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

function when(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function HistorySidebar({ conversations, activeId, onSelect, onNew, onDelete }: Props) {
  return (
    <aside className="w-64 shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col">
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium py-2 transition-colors"
        >
          <Plus className="w-4 h-4" /> New chat
        </button>
      </div>
      <p className="px-4 pb-1 text-xs uppercase tracking-wide text-gray-400">History</p>
      <nav className="flex-1 overflow-y-auto px-2 pb-3 space-y-1">
        {conversations.length === 0 && (
          <p className="px-2 py-3 text-xs text-gray-400">No conversations yet.</p>
        )}
        {conversations.map((c) => (
          <div
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`group flex items-start gap-2 rounded-lg px-2 py-2 cursor-pointer transition-colors ${
              c.id === activeId ? "bg-gray-800" : "hover:bg-gray-900"
            }`}
          >
            <MessageSquare className="w-4 h-4 mt-0.5 text-indigo-400 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-gray-100 truncate">{c.title}</p>
              <p className="text-xs text-gray-400">
                {when(c.updated_at)} · {c.message_count / 2} Q
              </p>
            </div>
            <button
              title="Delete conversation"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400 transition-opacity"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
