import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import QueryInput from "./components/QueryInput";
import HistorySidebar from "./components/HistorySidebar";
import { AssistantBubble, UserBubble } from "./components/ChatMessage";
import { ChatError, deleteConversation, getConversation, listConversations, sendChat } from "./api";
import type { ConversationSummary, StoredMessage } from "./types";

const ACTIVE_KEY = "sqlcopilot.activeConversation";

export default function App() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(() => localStorage.getItem(ACTIVE_KEY));
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [pending, setPending] = useState<string | null>(null); // question being answered
  const [loadError, setLoadError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshList = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load history.");
    }
  }, []);

  const open = useCallback(async (id: string | null) => {
    setActiveId(id);
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
    if (!id) {
      setMessages([]);
      return;
    }
    try {
      setMessages((await getConversation(id)).messages);
      setLoadError(null);
    } catch {
      // conversation no longer exists on the server
      setMessages([]);
      setActiveId(null);
      localStorage.removeItem(ACTIVE_KEY);
    }
  }, []);

  useEffect(() => {
    refreshList();
    if (activeId) open(activeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  const handleSend = async (question: string) => {
    setPending(question);
    try {
      const res = await sendChat(question, activeId);
      await open(res.conversation_id);
    } catch (err) {
      if (err instanceof ChatError && err.conversationId) await open(err.conversationId);
      else setLoadError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setPending(null);
      refreshList();
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Delete this conversation?")) return;
    await deleteConversation(id).catch(() => undefined);
    if (id === activeId) await open(null);
    refreshList();
  };

  const empty = messages.length === 0 && !pending;

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur z-10">
        <div className="px-6 py-4 flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-600">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white leading-none">SQL Copilot</h1>
            <p className="text-xs text-gray-300 leading-none mt-0.5">Sakila DVD-rental · PostgreSQL</p>
          </div>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <HistorySidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={(id) => open(id)}
          onNew={() => open(null)}
          onDelete={handleDelete}
        />

        <main className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-4xl mx-auto w-full px-6 py-8 space-y-6">
              {empty && (
                <div className="text-center py-12 space-y-3">
                  <h2 className="text-4xl font-bold text-white tracking-tight">Ask your database anything</h2>
                  <p className="text-gray-200 text-lg">
                    Type a question in plain English — follow-ups like &ldquo;now only for store 2&rdquo; work too.
                  </p>
                </div>
              )}

              {messages.map((m) =>
                m.role === "user" ? (
                  <UserBubble key={m.id} text={m.content} />
                ) : (
                  <AssistantBubble key={m.id} answer={m.content} error={m.error} result={m.result} />
                ),
              )}

              {pending && (
                <>
                  <UserBubble text={pending} />
                  <div className="h-24 rounded-2xl bg-gray-800 animate-pulse" />
                </>
              )}

              {loadError && <p className="text-sm text-red-300 whitespace-pre-wrap">{loadError}</p>}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t border-gray-800 bg-gray-950">
            <div className="max-w-4xl mx-auto w-full px-6 py-4">
              <QueryInput onSubmit={handleSend} loading={pending !== null} />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
