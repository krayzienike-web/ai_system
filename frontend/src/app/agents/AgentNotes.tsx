// «Помощник» (stage 9, ADR 0010): the agents' notes on the home screen. What a note says and lists is the
// server's; the screen only shows it and sends the person's answer — nothing happens without the button.
import { Link } from "@tanstack/react-router";
import {
  CalendarClock,
  ClipboardList,
  DatabaseZap,
  Hourglass,
  Sparkles,
} from "lucide-react";
import { useId, useState } from "react";

import { ApiError, DEMO } from "../../api/client";
import {
  useAgentNotes,
  useAnswerNote,
  useAppContext,
  useAskInventory,
  useMe,
} from "../../api/hooks";
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
  return e instanceof ApiError
    ? e.message
    : "Не получилось — попробуйте еще раз";
}

export function NoteCard({ note, hq }: { note: AgentNote; hq: boolean }) {
  const viewer = useViewer();
  const answer = useAnswerNote();
  const { notify } = useUi();
  const [all, setAll] = useState(false);
  const Icon = ICON[note.agent];
  const may =
    viewer?.can("tasks.assign") ||
    (note.audience === "director" && viewer?.can("tasks.execute"));
  const items = all ? note.items : note.items.slice(0, SHOWN);
  const send = (kind: "accept" | "dismiss") =>
    answer.mutate(
      { id: note.id, answer: kind },
      {
        onSuccess: (n) =>
          notify(
            kind === "dismiss"
              ? "Скрыли сообщение"
              : n.agent === "task_stuck"
                ? `Срок перенесен на ${ddmm(note.action_due_on)}`
                : "Задача создана — она в «Задачах»",
          ),
        onError: (e) => notify(errorText(e)),
      },
    );
  return (
    <li>
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <Icon size={18} className="mt-0.5 shrink-0 text-ink-2" aria-hidden />
          <div className="min-w-0 flex-1">
            {hq && (
              <div className="text-xs text-ink-2">{note.restaurant_name}</div>
            )}
            <h3 className="font-medium">{note.title}</h3>
            <p className="mt-1 text-sm text-ink-2">{note.text}</p>
            {items.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">
                {items.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {note.items.length > SHOWN && (
              <button
                type="button"
                className="mt-1 text-sm text-ink-2 underline"
                onClick={() => setAll(!all)}
              >
                {all ? "Свернуть" : `Показать все (${note.items.length})`}
              </button>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {may && note.action === "create_task" && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={answer.isPending}
                  onClick={() => send("accept")}
                >
                  Создать задачу
                </Button>
              )}
              {may && note.action === "move_due" && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={answer.isPending}
                  onClick={() => send("accept")}
                >
                  Перенести на {ddmm(note.action_due_on)}
                </Button>
              )}
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
              {may && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={answer.isPending}
                  onClick={() => send("dismiss")}
                >
                  {note.action ? "Не нужно" : "Скрыть"}
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>
    </li>
  );
}

/** A count on another day than expected: the director asks for the list for that day. */
function AskInventory({ restaurantId }: { restaurantId: string }) {
  const ask = useAskInventory();
  const { context } = useToday();
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState("");
  const id = useId();
  if (!context) return null;
  if (!open)
    return (
      <button
        type="button"
        className="text-sm text-ink-2 underline"
        onClick={() => setOpen(true)}
      >
        Пересчет в другой день? Подготовить список
      </button>
    );
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (day) ask.mutate({ restaurant_id: restaurantId, count_on: day });
      }}
    >
      <label htmlFor={id} className="text-sm">
        День пересчета
        <input
          id={id}
          type="date"
          required
          min={context.min}
          max={context.max}
          value={day}
          onChange={(e) => setDay(e.target.value)}
          className="mt-1 block rounded-md border border-line bg-surface px-2 py-1"
        />
      </label>
      <Button
        type="submit"
        size="sm"
        variant="primary"
        disabled={ask.isPending || !day}
      >
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

/** The server's «today» (the demo has its own), and two weeks ahead: the days a list can be asked for. */
function useToday() {
  const today = useAppContext().data?.today;
  if (!today) return { context: null };
  const max = new Date(Date.parse(today) + 14 * 86_400_000)
    .toISOString()
    .slice(0, 10);
  return { context: { min: today, max } };
}

/** «Помощник» on the home screen: nothing to say — nothing shown, except the director's «Подготовить список». */
export function AgentNotes() {
  const viewer = useViewer();
  const { data: me } = useMe();
  const notes = useAgentNotes();
  if (!viewer || !notes.data) return null;
  const restaurantId = me?.restaurant?.id;
  if (!notes.data.length && !restaurantId) return null;
  return (
    <section aria-labelledby="assistant" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2
          id="assistant"
          className="flex items-center gap-2 text-lg font-semibold"
        >
          <Sparkles size={18} aria-hidden /> Помощник
        </h2>
        {restaurantId && viewer.can("tasks.execute") && !DEMO && (
          <AskInventory restaurantId={restaurantId} />
        )}
      </div>
      {notes.data.length > 0 ? (
        <ul className="space-y-3">
          {notes.data.map((n) => (
            <NoteCard key={n.id} note={n} hq={viewer.isHq} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-2">
          Сейчас подсказать нечего: сроки в порядке, данные пришли.
        </p>
      )}
    </section>
  );
}
