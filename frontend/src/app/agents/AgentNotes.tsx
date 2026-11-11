// «Помощник» (stage 9, ADR 0010): the agents' notes on the home screen. What a note says and lists is the
// server's; the screen only shows it and sends the person's answer — nothing happens without the button.
import { Link } from "@tanstack/react-router";
import { CalendarClock, ClipboardList, DatabaseZap, Hourglass, Sparkles } from "lucide-react";
import { useId, useRef, useState } from "react";

import { ApiError, DEMO } from "../../api/client";
import { useAgentNotes, useAnswerNote, useAppContext, useAskInventory, useMe } from "../../api/hooks";
import type { AgentNote } from "../../api/types";
import { Button, Card } from "../../ds/primitives";
import { ddmm } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";

const ICON = {
  inventory_prep: ClipboardList,
  task_due: Hourglass,
  task_stuck: CalendarClock,
  data_check: DatabaseZap,
} as const;

const SHOWN = 5; // longer lists open on «Показать все»

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Не получилось — попробуйте еще раз";
}

/** Who may answer: as the server's `agents.service._may_answer` — the HQ admin any note, a director the notes to
 * the director; the HQ analyst reads only. */
export function mayAnswer(note: AgentNote, can: (permission: "tasks.assign" | "tasks.execute") => boolean): boolean {
  return can("tasks.assign") || (note.audience === "director" && can("tasks.execute"));
}

export function NoteCard({ note, hq, onAnswered }: { note: AgentNote; hq: boolean; onAnswered?: () => void }) {
  const viewer = useViewer();
  const answer = useAnswerNote();
  const { notify } = useUi();
  const [all, setAll] = useState(false);
  const titleId = useId();
  const Icon = ICON[note.agent];
  const may = viewer ? mayAnswer(note, viewer.can) : false;
  const items = all ? note.items : note.items.slice(0, SHOWN);
  const send = (kind: "accept" | "dismiss") =>
    answer.mutate(
      { id: note.id, answer: kind },
      {
        onSuccess: (n) => {
          onAnswered?.(); // the card goes away: focus stays in «Помощник», not on the page's body
          notify(
            kind === "dismiss"
              ? "Скрыли сообщение"
              : n.agent === "task_stuck"
                ? `Срок перенесен на ${ddmm(note.action_due_on)}`
                : "Задача создана — она в «Задачах»",
          );
        },
        onError: (e) => notify(errorText(e)),
      },
    );
  // Each button names its note for a screen reader: «Скрыть» of which of the three?
  const answerButton = (kind: "accept" | "dismiss", variant: "primary" | "ghost", label: string) => (
    <Button
      variant={variant}
      size="sm"
      aria-describedby={titleId}
      disabled={answer.isPending}
      onClick={() => send(kind)}
    >
      {label}
    </Button>
  );
  return (
    <li aria-labelledby={titleId}>
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <Icon size={18} className="mt-0.5 shrink-0 text-ink-2" aria-hidden />
          <div className="min-w-0 flex-1">
            {hq && <div className="text-xs text-ink-2">{note.restaurant_name}</div>}
            <h3 id={titleId} className="font-medium">
              {note.title}
            </h3>
            <p className="mt-1 text-sm text-ink-2">{note.text}</p>
            {items.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">
                {items.map((line, i) => (
                  <li key={`${i}-${line}`}>{line}</li>
                ))}
              </ul>
            )}
            {note.items.length > SHOWN && (
              <button type="button" className="mt-1 text-sm text-ink-2 underline" onClick={() => setAll(!all)}>
                {all ? "Свернуть" : `Показать все (${note.items.length})`}
              </button>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {may && note.action === "create_task" && answerButton("accept", "primary", "Создать задачу")}
              {may &&
                note.action === "move_due" &&
                answerButton("accept", "primary", `Перенести на ${ddmm(note.action_due_on)}`)}
              {note.agent === "data_check" && (
                <Link to="/data" className="text-sm font-medium underline">
                  Загрузить на экране «Данные»
                </Link>
              )}
              {(note.agent === "task_due" || note.agent === "task_stuck") && (
                <Link to="/tasks" className="text-sm font-medium underline">
                  Открыть задачи
                </Link>
              )}
              {may && answerButton("dismiss", "ghost", note.action ? "Не нужно" : "Скрыть")}
            </div>
          </div>
        </div>
      </Card>
    </li>
  );
}

/** The server's «today» (the demo has its own), and two weeks ahead: the days a list can be asked for. */
export function askRange(today: string): { min: string; max: string } {
  const max = new Date(Date.parse(today) + 14 * 86_400_000).toISOString().slice(0, 10);
  return { min: today, max };
}

/** A count on another day than expected: the director asks for the list for that day. */
function AskInventory({ restaurantId, onReady }: { restaurantId: string; onReady: () => void }) {
  const ask = useAskInventory();
  const { notify } = useUi();
  const today = useAppContext().data?.today;
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState("");
  const id = useId();
  if (!today) return null;
  const range = askRange(today);
  if (!open)
    return (
      <button type="button" className="text-sm text-ink-2 underline" onClick={() => setOpen(true)}>
        Пересчет в другой день? Подготовить список
      </button>
    );
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!day) return;
        ask.mutate(
          { restaurant_id: restaurantId, count_on: day },
          {
            onSuccess: () => {
              setOpen(false);
              setDay("");
              notify("Список готов — он в «Помощнике»");
              onReady();
            },
          },
        );
      }}
    >
      <label htmlFor={id} className="text-sm">
        День пересчета
        <input
          id={id}
          type="date"
          required
          min={range.min}
          max={range.max}
          value={day}
          onChange={(e) => setDay(e.target.value)}
          className="mt-1 block rounded-md border border-line bg-surface px-2 py-1"
        />
      </label>
      <Button type="submit" size="sm" variant="primary" disabled={ask.isPending || !day}>
        Подготовить
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Отмена
      </Button>
      {ask.isError && (
        <p role="alert" className="w-full text-sm text-loss">
          {errorText(ask.error)}
        </p>
      )}
    </form>
  );
}

/** «Помощник» on the home screen: nothing to say — nothing shown, except the director's «Подготовить список». */
export function AgentNotes() {
  const viewer = useViewer();
  const { data: me } = useMe();
  const notes = useAgentNotes();
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const focusHeading = () => heading.current?.focus();
  const restaurantId = me?.restaurant?.id;
  if (!viewer) return null;
  if (notes.isError && !notes.data)
    return (
      <p role="alert" className="text-sm text-loss">
        Помощник не загрузился — обновите страницу
      </p>
    );
  if (!notes.data) return null;
  if (!notes.data.length && !restaurantId) return null;
  return (
    <section aria-labelledby={headingId} className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2
          id={headingId}
          ref={heading}
          tabIndex={-1}
          className="flex items-center gap-2 text-lg font-semibold outline-none"
        >
          <Sparkles size={18} aria-hidden /> Помощник
        </h2>
        {restaurantId && viewer.can("tasks.execute") && !DEMO && (
          <AskInventory restaurantId={restaurantId} onReady={focusHeading} />
        )}
      </div>
      {notes.data.length > 0 ? (
        <ul className="space-y-3">
          {notes.data.map((n) => (
            <NoteCard key={n.id} note={n} hq={viewer.isHq} onAnswered={focusHeading} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-2">Сейчас подсказать нечего: сроки в порядке, данные пришли.</p>
      )}
    </section>
  );
}
