import { Link } from "@tanstack/react-router";
import { Send, Sparkles, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { answer, type ChatAnswer, suggestionsFor } from "../lib/chatScript";
import { useViewer } from "../lib/useViewer";
import { type ChatContextRef, usePrototype } from "../state/prototype";
import { Button, cx } from "./ui";

interface Message {
  role: "user" | "assistant";
  text: string;
  answer?: ChatAnswer;
}

export function ChatPanel({ context, className }: { context: ChatContextRef | null; className?: string }) {
  const viewer = useViewer();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing]);

  if (!viewer) return null;

  function ask(text: string) {
    if (!text.trim() || !viewer) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setTyping(true);
    window.setTimeout(() => {
      const a = answer(text, viewer, context?.findingId);
      setMessages((m) => [...m, { role: "assistant", text: a.text, answer: a }]);
      setTyping(false);
    }, 700);
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(input);
  };

  const starters = context?.findingId ? ["Почему так получилось?", "Что мне сделать?", "Сколько это в рублях за год?"] : suggestionsFor(viewer);

  return (
    <div className={cx("flex min-h-0 flex-col", className)}>
      {context && (
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-600">
          Обсуждаем: <span className="font-medium text-slate-800">{context.title}</span>
        </div>
      )}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="text-sm text-slate-500">
            Задайте вопрос о данных {viewer.isHq ? "сети" : "вашего ресторана"}. Ответ строится только на посчитанных системой цифрах.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cx("max-w-[92%] rounded-lg px-3 py-2 text-sm", m.role === "user" ? "ml-auto bg-slate-900 text-white" : "bg-slate-100 text-slate-800")}>
            <div className="whitespace-pre-line">{m.text}</div>
            {m.answer?.table && (
              <div className="mt-2 overflow-x-auto rounded-md bg-white">
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-500">
                    <tr>
                      {m.answer.table.columns.map((c) => (
                        <th key={c} className="px-2 py-1 font-normal">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {m.answer.table.rows.map((row, r) => (
                      <tr key={r} className="border-t border-slate-100">
                        {row.map((cell, c) => (
                          <td key={c} className="px-2 py-1">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(m.answer?.source || m.answer?.sourceFindingId) && (
              <div className="mt-2 text-xs text-slate-500">
                Откуда цифры: {m.answer.source}
                {m.answer.sourceFindingId && (
                  <>
                    {m.answer.source ? " · " : ""}
                    <Link to="/insights/$findingId" params={{ findingId: m.answer.sourceFindingId }} className="underline">
                      карточка находки
                    </Link>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {typing && <div className="w-16 animate-pulse rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-500">···</div>}
        <div ref={endRef} />
      </div>
      <div className="border-t border-slate-200 p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {starters.map((s) => (
            <button key={s} type="button" onClick={() => ask(s)} className="rounded-full border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50">
              {s}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Спросите о данных…"
            aria-label="Вопрос ассистенту"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <Button type="submit" variant="primary" aria-label="Отправить">
            <Send size={14} />
          </Button>
        </form>
      </div>
    </div>
  );
}

/** Right-side drawer available on every screen; reopening with a new context starts a new thread. */
export function ChatDrawer() {
  const { chat, closeChat } = usePrototype();
  if (!chat.open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/20" onClick={closeChat}>
      <aside
        className="flex h-full w-full max-w-md flex-col bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
        aria-label="Ассистент"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2 font-medium">
            <Sparkles size={16} /> Ассистент
          </div>
          <Button variant="ghost" onClick={closeChat} aria-label="Закрыть">
            <X size={16} />
          </Button>
        </div>
        <ChatPanel key={chat.context?.findingId ?? "general"} context={chat.context} className="flex-1" />
      </aside>
    </div>
  );
}
