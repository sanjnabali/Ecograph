"use client";
/**
 * app/chat/page.tsx - AI Chat interface.
 * Sends questions to POST /api/chat/message, shows streaming-like response.
 */
import { useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { api, ApiError } from "@/lib/api";
import { truncate } from "@/lib/utils";

interface Message {
  role:          "user" | "assistant";
  content:       string;
  context_used?: boolean;
  sources?:      string[];
  error?:        boolean;
}

// -- Single chat bubble ---------------------------------------------------
function Bubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} gap-2`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-brand-700 flex items-center justify-center text-sm shrink-0">
        </div>
      )}
      <div
        className={`max-w-2xl rounded-2xl px-4 py-3 text-sm ${
          isUser
            ? "bg-brand-700 text-white rounded-tr-sm"
            : msg.error
            ? "bg-red-950 border border-red-800 text-red-200 rounded-tl-sm"
            : "bg-gray-800 text-gray-100 rounded-tl-sm"
        }`}
      >
        {isUser ? (
          <p>{msg.content}</p>
        ) : (
          <ReactMarkdown
            components={{
              p:    ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
              code: ({ children }) => (
                <code className="bg-gray-700 px-1 rounded text-green-300 text-xs font-mono">{children}</code>
              ),
              ul:   ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
              li:   ({ children }) => <li className="text-sm">{children}</li>,
            }}
          >
            {msg.content}
          </ReactMarkdown>
        )}

        {/* Source tags */}
        {!isUser && msg.sources && msg.sources.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-gray-700">
            {msg.sources.map(s => (
              <span key={s} className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">
                {truncate(s, 24)}
              </span>
            ))}
          </div>
        )}

        {/* Context indicator */}
        {!isUser && msg.context_used === false && !msg.error && (
          <p className="text-xs text-gray-500 mt-1 italic">
            No graph context found - answered from general knowledge.
          </p>
        )}
      </div>
    </div>
  );
}

// -- Typing indicator -----------------------------------------------------
function TypingIndicator() {
  return (
    <div className="flex justify-start gap-2">
      <div className="w-8 h-8 rounded-full bg-brand-700 flex items-center justify-center text-sm shrink-0">
        
      </div>
      <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-4">
          {[0, 1, 2].map(i => (
            <div
              key={i}
              className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// -- Main page ------------------------------------------------------------
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([{
    role:    "assistant",
    content: "Hi! I'm EcoGraph AI. Ask me anything about the Scope 3 emissions, suppliers, or net-zero targets in your graph.",
  }]);
  const [input,    setInput]    = useState("");
  const [sending,  setSending]  = useState(false);
  const bottomRef               = useRef<HTMLDivElement>(null);

  const suggestionsQ = useQuery({
    queryKey: ["suggestions"],
    queryFn:  api.getSuggestions,
  });

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const send = async (question: string) => {
    if (!question.trim() || sending) return;

    const userMsg: Message = { role: "user", content: question };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setSending(true);

    // Build history (exclude first system greeting)
    const history = messages.slice(1).map(m => ({
      role:    m.role,
      content: m.content,
    }));

    try {
      const res = await api.sendMessage(question, history);
      setMessages(prev => [
        ...prev,
        {
          role:         "assistant",
          content:      res.answer,
          context_used: res.context_used,
          sources:      res.sources,
        },
      ]);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      const isQuota = err instanceof ApiError && err.status === 429;
      const isMiskey = err instanceof ApiError && err.code === "missing_api_key";
      const hint = isQuota
        ? "\n\n_You've hit the Gemini free-tier rate limit. Wait ~1 minute and try again._"
        : isMiskey
        ? "\n\n_Set GOOGLE\\_API\\_KEY in your `.env` file and restart the backend._"
        : "";
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: msg + hint, error: true },
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-white">Ask the Graph</h1>
        <p className="text-gray-400 text-sm mt-1">
          AI answers grounded in your Neo4j ESG knowledge graph
        </p>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 pb-4">
        {messages.map((msg, i) => (
          <Bubble key={i} msg={msg} />
        ))}
        {sending && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      {messages.length <= 1 && suggestionsQ.data && (
        <div className="flex flex-wrap gap-2 mb-3">
          {suggestionsQ.data.slice(0, 4).map((s: any) => (
            <button
              key={s.question}
              onClick={() => send(s.question)}
              className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-full border border-gray-700 transition-colors"
            >
              {s.question}
            </button>
          ))}
        </div>
      )}

      {/* Input bar */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={sending}
          placeholder="Ask about Scope 3 emissions, suppliers, targets..."
          className="flex-1 bg-gray-800 border border-gray-700 text-white text-sm px-4 py-3 rounded-xl placeholder-gray-500 focus:outline-none focus:border-brand-500 disabled:opacity-50 transition-colors"
          maxLength={1000}
        />
        <button
          type="submit"
          disabled={!input.trim() || sending}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 py-3 rounded-xl font-medium text-sm transition-colors"
        >
          {sending ? "..." : "Send"}
        </button>
      </form>

      <p className="text-gray-600 text-xs text-center mt-2">
        Powered by Gemini 1.5 Flash • Free tier: 15 req/min
      </p>
    </div>
  );
}