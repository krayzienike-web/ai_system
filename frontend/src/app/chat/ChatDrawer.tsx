import { useNavigate } from "@tanstack/react-router";
import { ArrowUp, Calculator, ExternalLink, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { LogoMark } from "../../brand/Logo";
import { useAppContext, useAsk, useChatSuggestions, useCreateTasks, useFinding } from "../../api/hooks";
import type { ChatAnswer } from "../../api/types";
import { Button, cx, EASE } from "../../ds/primitives";
import { useViewer } from "../../lib/useViewer";
import { type ChatContextRef, useUi } from "../../state/ui";

interface Message {
  role: "user" | "assistant";
  text: string;
  answer?: ChatAnswer;
}

/** Reveals assistant text progressively ("typing"), then the table. */
function Typed({ text, onDone }: { text: string; onDone: () => void }) {
  const reduce = useReducedMotion();
  const [n, setN] = useState(0);
  useEffect(() => {
    if (reduce) {
      onDone();
      return;
    }
    let shown = 0;
    const id = window.setInterval(() => {
      shown = Math.min(text.length, shown + 4);
      setN(shown);
      if (shown >= text.length) {
        window.clearInterval(id);
        onDone();
      }
    }, 16);
    return () => window.clearInterval(id);
  }, [text, reduce, onDone]);
  return <span className="whitespace-pre-line">{reduce ? text : text.slice(0, n)}</span>;
}

function AssistantMessage({ m, last }: { m: Message; last: boolean }) {
  const [done, setDone] = useState(!last);
  const finish = useCallback(() => setDone(true), []);
  const a = m.answer;
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 shrink-0">
        <LogoMark size={26} />
      </span>
      <div className="min-w-0 flex-1 rounded-[14px] rounded-tl-sm bg-paper px-3.5 py-2.5 text-sm leading-relaxed text-ink">
        {last ? <Typed text={m.text} onDone={finish} /> : <span className="whitespace-pre-line">{m.text}</span>}
        {done && a && a.rows.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="mt-3 overflow-x-auto rounded-[10px] border border-line bg-surface"
          >
            <table className="w-full text-[13px]">
              <thead className="bg-paper/60 text-left text-ink-3">
                <tr>
                  {a.columns.map((c) => (
                    <th key={c} className="px-2.5 py-1.5 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="num">
                {a.rows.map((row, r) => (
                  <tr key={r} className="border-t border-line">
                    {row.map((cell, c) => (
                      <td key={c} className="px-2.5 py-1.5">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </motion.div>
        )}
        {done && a && (a.source || a.source_finding_id) && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-ink-3">
            {a.source && (
              <span className="inline-flex items-center gap-1">
                <Calculator size={12} aria-hidden /> {a.source}
              </span>
            )}
            {a.source_finding_id && <FindingLinks id={a.source_finding_id} />}
          </div>
        )}
      </div>
    </div>
  );
}

/** «Открыть находку» and, for a director whose finding nobody took yet, «Взять в работу». */
function FindingLinks({ id }: { id: string }) {
  const navigate = useNavigate();
  const viewer = useViewer();
  const { closeChat, notify } = useUi();
  const finding = useFinding(id);
  const create = useCreateTasks();
  const context = useAppContext();
  const f = finding.data;
  const week = context.data?.due_options.find((o) => o.days === 7);
  const canTake = f && !viewer?.isHq && f.work.stage === "new" && f.restaurant_id;
  return (
    <>
      <button
        type="button"
        className="inline-flex items-center gap-1 font-medium text-brand-strong hover:underline"
        onClick={() => {
          closeChat();
          void navigate({ to: "/findings/$findingId", params: { findingId: id } });
        }}
      >
        Открыть находку <ExternalLink size={11} />
      </button>
      {canTake && week && (
        <Button
          size="sm"
          variant="primary"
          disabled={create.isPending}
          onClick={() =>
            create.mutate(
              { title: f.actions[0] ?? f.title, finding_id: f.id, due_on: week.due_on },
              { onSuccess: () => notify("Задача в «Моих задачах»") },
            )
          }
        >
          Взять в работу
        </Button>
      )}
    </>
  );
}

export function ChatPanel({ context, className }: { context: ChatContextRef | null; className?: string }) {
  const viewer = useViewer();
  const asking = useAsk();
  const suggestions = useChatSuggestions();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, thinking]);

  if (!viewer) return null;

  function ask(text: string) {
    if (!text.trim() || !viewer || thinking) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setThinking(true);
    asking.mutate(
      { question: text, finding_id: context?.findingId },
      {
        onSuccess: (a) => setMessages((m) => [...m, { role: "assistant", text: a.text, answer: a }]),
        onError: () => setMessages((m) => [...m, { role: "assistant", text: "Не получилось ответить. Попробуйте еще раз." }]),
        onSettled: () => setThinking(false),
      },
    );
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(input);
  };

  const starters = context?.findingId
    ? ["Почему так получилось?", "Что мне сделать?", "Сколько это в рублях за год?"]
    : (suggestions.data ?? []);

  return (
    <div className={cx("flex min-h-0 flex-col", className)}>
      {context && (
        <div className="border-b border-line bg-brand-soft px-5 py-2.5 text-[13px] text-brand-strong">
          Говорим о: <span className="font-semibold">{context.title}</span>
        </div>
      )}
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.length === 0 && (
          <div className="rounded-[14px] border border-line bg-surface p-4 text-sm text-ink-2">
            <div className="mb-1 font-medium text-ink">Здравствуйте! Я су-шеф.</div>
            Спросите что угодно о данных {viewer.isHq ? "сети" : "вашего ресторана"} — отвечу цифрами, которые посчитала система, и
            покажу, откуда они.
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ml-auto w-fit max-w-[85%] rounded-[14px] rounded-tr-sm bg-ink px-3.5 py-2 text-sm text-white">
              {m.text}
            </div>
          ) : (
            <AssistantMessage key={i} m={m} last={i === messages.length - 1} />
          ),
        )}
        {thinking && (
          <div className="flex items-center gap-2.5 text-sm text-ink-3">
            <LogoMark size={26} />
            <span className="flex gap-1" aria-label="Су-шеф думает">
              {[0, 1, 2].map((d) => (
                <motion.span
                  key={d}
                  className="h-1.5 w-1.5 rounded-full bg-brand"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 0.9, repeat: Infinity, delay: d * 0.15 }}
                />
              ))}
            </span>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="border-t border-line p-4">
        <div className="mb-3 flex flex-wrap gap-1.5">
          {starters.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => ask(s)}
              className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-xs text-ink-2 transition hover:border-brand hover:text-ink"
            >
              {s}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="flex items-center gap-2 rounded-full border border-line-strong bg-surface py-1 pr-1 pl-4 focus-within:border-brand">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Спросите своими словами…"
            aria-label="Вопрос су-шефу"
            className="min-w-0 flex-1 bg-transparent py-1.5 text-sm outline-none"
          />
          <button type="submit" aria-label="Отправить" className="grid h-9 w-9 place-items-center rounded-full bg-brand text-white hover:bg-brand-strong">
            <ArrowUp size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}

export function ChatDrawer() {
  const { chat, closeChat } = useUi();
  return (
    <AnimatePresence>
      {chat.open && (
        <motion.div
          className="fixed inset-0 z-40 flex justify-end bg-ink/25"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={closeChat}
        >
          <motion.aside
            className="flex h-full w-full max-w-[460px] flex-col bg-surface shadow-[var(--shadow-float)]"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
            onClick={(e) => e.stopPropagation()}
            aria-label="Су-шеф"
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <div className="flex items-center gap-2 font-display font-semibold">
                <Sparkles size={16} className="text-brand" /> Су-шеф
              </div>
              <Button variant="ghost" size="sm" onClick={closeChat} aria-label="Закрыть">
                <X size={16} />
              </Button>
            </div>
            <ChatPanel key={chat.context?.findingId ?? "general"} context={chat.context} className="flex-1" />
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
