// «Задачи сети» (Q39): every task of the network for the HQ — by findings, by checks, by the agents
// (a transfer between restaurants has no finding) and the directors' own. The HQ follows them here and
// reminds a director of an overdue one; the restaurant does the work in its own «Задачи».
import { Link } from "@tanstack/react-router";
import { BellRing, RotateCcw } from "lucide-react";
import { useState } from "react";

import { useAppContext, useRestaurants, useTaskAction, useTasks } from "../../api/hooks";
import type { ApiTask } from "../../api/types";
import { Button, Card, cx, EmptyState, ErrorText, LoadError, PageTitle, Pill, Reveal, Skeleton } from "../../ds/primitives";
import { ddmm, plural } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";

type Show = "open" | "late" | "loose" | "done";

const SHOWS: { key: Show; label: string; pick: (t: ApiTask) => boolean }[] = [
  { key: "open", label: "В работе", pick: (t) => t.status !== "done" },
  { key: "late", label: "Просрочены", pick: (t) => t.late },
  // Not from a finding or a check: the agents' transfers, the HQ's own, the directors' own.
  { key: "loose", label: "Без находки", pick: (t) => t.status !== "done" && !t.finding_id && !t.experiment_id },
  { key: "done", label: "Сделаны", pick: (t) => t.status === "done" },
];

const select =
  "h-10 rounded-[10px] border border-line-strong bg-surface px-3 text-sm text-ink outline-none transition hover:border-ink-3 focus:border-brand";

/** When, in words — as the restaurant sees it in its list. */
export function dueText(t: ApiTask) {
  if (t.status === "done") return t.done_on ? `сделано ${ddmm(t.done_on)}` : "сделано";
  if (t.days_left < 0) return `просрочено на ${plural(-t.days_left, ["день", "дня", "дней"])}`;
  if (t.days_left === 0) return "срок сегодня";
  return `до ${ddmm(t.due_on)}`;
}

function TaskRow({ task, mayRemind, today }: { task: ApiTask; mayRemind: boolean; today: string | undefined }) {
  const remindedToday = !!today && task.reminded_on === today;
  const action = useTaskAction();
  const { notify } = useUi();
  const steps = task.checklist.length;
  const ticked = task.checklist_done.filter(Boolean).length;
  const done = task.status === "done";
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 py-4">
      {/* At least 16rem for the words: on a phone the deadline and the button go under them. */}
      <div className="min-w-0 flex-[1_1_16rem]">
        <div className="font-medium text-ink">{task.title}</div>
        <div className="mt-0.5 text-sm text-ink-3">
          {task.restaurant_name}
          {" · "}
          {task.finding_id && task.finding_title ? (
            <Link to="/findings/$findingId" params={{ findingId: task.finding_id }} className="hover:text-ink">
              {task.finding_title} →
            </Link>
          ) : (
            (task.source ?? "Без находки")
          )}
          {steps > 0 && !done && ` · шаги ${ticked} из ${steps}`}
          {task.reminded_on && !done && ` · напомнили ${ddmm(task.reminded_on)}`}
        </div>
        {done && task.report && <div className="mt-1 text-sm text-ink-2">Отчет: {task.report}</div>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <span className={cx("text-sm", task.late ? "font-medium text-loss" : done ? "text-gain" : "text-ink-3")}>{dueText(task)}</span>
        {!done && task.status === "in_progress" && <Pill tone="info">начата</Pill>}
        {task.late && mayRemind && (
          <Button
            size="sm"
            // Once a day is enough (tasks/service.py `remind`); the button names its task (review, pp. 6, 7).
            disabled={action.isPending || remindedToday}
            aria-label={`${remindedToday ? "Напомнили сегодня" : "Напомнить"}: ${task.title}, ${task.restaurant_name ?? ""}`}
            onClick={() =>
              action.mutate({ id: task.id, action: "remind" }, { onSuccess: () => notify("Директору отправлено напоминание") })
            }
          >
            <BellRing size={14} /> {remindedToday ? "Напомнили сегодня" : task.reminded_on ? "Напомнить еще раз" : "Напомнить"}
          </Button>
        )}
      </div>
      <ErrorText error={action.error} className="w-full" />
    </li>
  );
}

export function NetworkTasks() {
  const viewer = useViewer();
  const query = useTasks();
  const restaurants = useRestaurants();
  const today = useAppContext().data?.today;
  const [show, setShow] = useState<Show>("open");
  const [where, setWhere] = useState("all");
  if (query.isError && !query.data)
    return (
      <div className="mx-auto max-w-[960px]">
        <LoadError error={query.error} title="Не получилось загрузить задачи" retry={() => void query.refetch()} />
      </div>
    );
  if (!query.data) return <Skeleton className="mx-auto h-96 max-w-[960px]" />;
  const all = query.data.filter((t) => where === "all" || t.restaurant_id === where);
  const open = all.filter((t) => t.status !== "done");
  const late = open.filter((t) => t.late);
  const current = SHOWS.find((s) => s.key === show)!;
  const shown = all
    .filter(current.pick)
    // Overdue first, then by deadline; done ones — the latest first.
    .sort((a, b) => (show === "done" ? (b.done_on ?? "").localeCompare(a.done_on ?? "") : a.days_left - b.days_left));
  const mayRemind = viewer?.can("tasks.assign") ?? false;

  return (
    <div className="mx-auto max-w-[960px]">
      <PageTitle
        title="Задачи сети"
        subtitle={
          late.length
            ? `${plural(open.length, ["задача", "задачи", "задач"])} в работе, из них просрочено: ${late.length}`
            : `${plural(open.length, ["задача", "задачи", "задач"])} в работе, просрочек нет`
        }
      />
      <Reveal>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select value={where} onChange={(e) => setWhere(e.target.value)} aria-label="Ресторан" className={select}>
            <option value="all">Все рестораны</option>
            {(restaurants.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <div className="flex max-w-full overflow-x-auto rounded-[10px] border border-line-strong bg-surface p-0.5" role="group" aria-label="Какие задачи">
            {SHOWS.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => setShow(s.key)}
                aria-pressed={show === s.key}
                className={cx(
                  "h-9 shrink-0 whitespace-nowrap rounded-[8px] px-3 text-sm transition-colors",
                  show === s.key ? "bg-ink text-white" : "text-ink-2 hover:text-ink",
                )}
              >
                {s.label} <span className="num opacity-60">{all.filter(s.pick).length}</span>
              </button>
            ))}
          </div>
          {(show !== "open" || where !== "all") && (
            <button
              type="button"
              onClick={() => {
                setShow("open");
                setWhere("all");
              }}
              className="inline-flex h-10 items-center gap-1.5 px-2 text-sm text-ink-3 hover:text-ink"
            >
              <RotateCcw size={14} /> Сбросить
            </button>
          )}
        </div>
      </Reveal>
      <Reveal index={1}>
        {shown.length ? (
          <Card className="px-5">
            <ul className="divide-y divide-line">
              {shown.map((t) => (
                <TaskRow key={t.id} task={t} mayRemind={mayRemind} today={today} />
              ))}
            </ul>
          </Card>
        ) : (
          <EmptyState title="Таких задач нет">Задачи ставятся из находок, проверок и сообщений помощника.</EmptyState>
        )}
      </Reveal>
    </div>
  );
}
