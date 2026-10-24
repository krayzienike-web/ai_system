import { Link } from "@tanstack/react-router";
import { Check, CheckCircle2, Clock, Plus, XCircle } from "lucide-react";
import { motion } from "motion/react";
import { type FormEvent, useState } from "react";

import { Button, cx, EASE } from "../../ds/primitives";
import { dateIn, daysUntil, DUE_PRESETS, todayLabel } from "../../lib/dates";
import { perMonth } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { RESTAURANTS } from "../../mock/data";
import { findingById } from "../../mock/selectors";
import type { Finding, Task, TaskOutcome } from "../../mock/types";
import { usePrototype } from "../../state/prototype";
import { useTasks } from "../counts";

const restaurantName = (code: string) => RESTAURANTS.find((r) => r.code === code)?.name ?? code;

/** The measured result of a task in one line: worked (₽) / did not work / not measured yet. */
export function OutcomePill({ outcome }: { outcome?: TaskOutcome }) {
  if (!outcome) return null;
  if (outcome.verdict === "confirmed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-gain-soft px-2.5 py-1 text-xs font-semibold text-gain">
        <CheckCircle2 size={13} /> Сработало{outcome.effectRubMonth ? `: +${perMonth(outcome.effectRubMonth)}` : ""}
      </span>
    );
  }
  if (outcome.verdict === "not_confirmed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-loss-soft px-2.5 py-1 text-xs font-semibold text-loss">
        <XCircle size={13} /> Не сработало
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-info-soft px-2.5 py-1 text-xs font-medium text-info">
      <Clock size={13} /> Результат считаем
    </span>
  );
}

type StepState = "done" | "current" | "todo" | "good" | "bad";

const DOT: Record<StepState, string> = {
  done: "border-brand bg-brand text-white",
  current: "border-brand bg-surface text-brand",
  todo: "border-line-strong bg-surface text-transparent",
  good: "border-gain-icon bg-gain-icon text-white",
  bad: "border-loss-icon bg-loss-icon text-white",
};

/**
 * Traceability of one task: found → task set → done (report) → result in ₽.
 * The result is computed by code after the recount or the check, never typed by a person.
 */
export function TaskTrace({ task, showFinding = true, showRestaurant = false }: { task: Task; showFinding?: boolean; showRestaurant?: boolean }) {
  const viewer = useViewer();
  const finding = task.findingId ? findingById(task.findingId) : undefined;
  const done = task.status === "done";
  const late = !done && (task.status === "overdue" || daysUntil(task.due) < 0);
  const o = task.outcome;

  const steps: { title: string; state: StepState; body: React.ReactNode }[] = [
    {
      title: "Нашли",
      state: "done",
      body: finding ? (
        showFinding ? (
          <Link to="/findings/$findingId" params={{ findingId: finding.id }} className="text-brand-strong hover:underline">
            {finding.title}
          </Link>
        ) : (
          <span className="text-ink-2">{finding.title}</span>
        )
      ) : (
        <span className="text-ink-2">{task.source}</span>
      ),
    },
    {
      title: "Поставили задачу",
      state: "done",
      body: (
        <span className="text-ink-2">
          {task.createdAt} · {task.assignedBy === "hq" ? "управляющая компания" : "директор"}
          {showRestaurant && ` → ${restaurantName(task.restaurantId)}`} · срок {task.due}
        </span>
      ),
    },
    {
      title: "Выполнили",
      state: done ? "done" : late ? "bad" : "current",
      body: done ? (
        <span className="text-ink-2">
          {task.doneAt}
          {task.report && <span className="mt-1 block rounded-[10px] bg-paper px-3 py-2 text-ink">«{task.report}»</span>}
        </span>
      ) : (
        <span className={late ? "font-medium text-loss" : "text-ink-3"}>{late ? `Просрочено, срок был ${task.due}` : `В работе, срок до ${task.due}`}</span>
      ),
    },
    {
      title: "Результат",
      state: !o ? "todo" : o.verdict === "confirmed" ? "good" : o.verdict === "not_confirmed" ? "bad" : "current",
      body: o ? (
        <span className="block space-y-1">
          <OutcomePill outcome={o} />
          <span className="block text-ink-2">
            {o.text}
            {o.measuredOn && <span className="text-ink-3"> · посчитано {o.measuredOn}</span>}
          </span>
          {task.experimentId && viewer?.isHq && (
            <Link to="/checks/$checkId" params={{ checkId: task.experimentId }} className="inline-block text-brand-strong hover:underline">
              Как проверяли →
            </Link>
          )}
        </span>
      ) : (
        <span className="text-ink-3">Посчитаем по данным после выполнения</span>
      ),
    },
  ];

  return (
    <ol className="relative space-y-3 text-sm" aria-label="История задачи">
      {steps.map((s, i) => (
        <motion.li
          key={s.title}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: i * 0.08 }}
          className="relative grid grid-cols-[20px_1fr] gap-3"
        >
          {i < steps.length - 1 && <span className="absolute top-5 bottom-[-12px] left-[9px] w-0.5 bg-line" aria-hidden />}
          <span className={cx("relative z-[1] mt-0.5 grid h-5 w-5 place-items-center rounded-full border-2", DOT[s.state])}>
            {s.state === "bad" ? <XCircle size={12} /> : s.state === "current" ? <span className="h-1.5 w-1.5 rounded-full bg-brand" /> : <Check size={11} strokeWidth={3} />}
          </span>
          <span className="min-w-0">
            <span className={cx("block text-xs font-semibold tracking-[0.04em] uppercase", s.state === "todo" ? "text-ink-3" : "text-ink")}>{s.title}</span>
            <span className="mt-0.5 block">{s.body}</span>
          </span>
        </motion.li>
      ))}
    </ol>
  );
}

/** Builds tasks for one step: one per restaurant (a network-wide finding goes to every director). */
function stepTasks(f: Finding, step: string, index: number, byHq: boolean, days: number): Task[] {
  const codes = f.restaurantId ? [f.restaurantId] : RESTAURANTS.map((r) => r.code);
  return codes.map((code) => ({
    id: `q-${f.id}-${index}-${code}`,
    restaurantId: code,
    title: step,
    source: byHq ? "Поставлено управляющей компанией" : "Взято директором из находки",
    findingId: f.id,
    assignedBy: byHq ? "hq" : "director",
    createdAt: todayLabel(),
    due: dateIn(days),
    status: "assigned",
  }));
}

/** "Что сделать" with a one-click task on every step: HQ assigns it to the director, a director takes it. */
export function QuickSteps({ f }: { f: Finding }) {
  const viewer = useViewer();
  const tasks = useTasks();
  const { createTasks } = usePrototype();
  const [days, setDays] = useState<number>(DUE_PRESETS[1].days);
  if (!viewer) return null;
  const byHq = viewer.isHq;
  const forWhom = f.restaurantId ? (byHq ? "директору" : "себе") : "всем директорам";

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Что сделать</span>
        <span className="flex items-center gap-1 text-xs text-ink-3">
          Срок:
          {DUE_PRESETS.map((p) => (
            <button
              key={p.days}
              type="button"
              aria-pressed={days === p.days}
              onClick={() => setDays(p.days)}
              className={cx("rounded-full px-2 py-0.5", days === p.days ? "bg-brand-soft font-medium text-brand-strong" : "hover:text-ink")}
            >
              {p.label.toLowerCase()}
            </button>
          ))}
        </span>
      </div>
      <ol className="mt-2 space-y-2 text-sm">
        {f.actions.map((a, i) => {
          const existing = tasks.filter((t) => t.findingId === f.id && t.title === a);
          return (
            <li key={a} className="flex flex-wrap items-start gap-3 rounded-[12px] border border-line p-3">
              <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand-strong">{i + 1}</span>
              <span className="min-w-0 flex-1 pt-0.5">{a}</span>
              {existing.length ? (
                byHq ? (
                  <span className="inline-flex items-center gap-1 pt-0.5 text-xs font-medium text-brand-strong">
                    <Check size={13} /> Поставлено до {existing[0]!.due}
                    {existing.length > 1 && ` · ${existing.length} рест.`}
                  </span>
                ) : (
                  <Link to="/tasks" className="inline-flex items-center gap-1 pt-0.5 text-xs font-medium text-brand-strong hover:underline">
                    <Check size={13} /> Задача до {existing[0]!.due} →
                  </Link>
                )
              ) : (
                <Button
                  size="sm"
                  onClick={() =>
                    createTasks(
                      stepTasks(f, a, i, byHq, days),
                      byHq ? `Задача поставлена ${forWhom}, срок ${dateIn(days)}` : `Задача в «Моих задачах», срок ${dateIn(days)}`,
                    )
                  }
                >
                  <Plus size={14} /> {byHq ? `Поставить ${forWhom}` : "В мои задачи"}
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** One-line task creation without a finding: what, where, by when. */
export function QuickTaskForm() {
  const viewer = useViewer();
  const { createTasks } = usePrototype();
  const [title, setTitle] = useState("");
  const [where, setWhere] = useState("all");
  const [days, setDays] = useState<number>(DUE_PRESETS[1].days);
  if (!viewer) return null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = title.trim();
    if (!text) return;
    const codes = viewer.isHq ? (where === "all" ? RESTAURANTS.map((r) => r.code) : [where]) : [viewer.restaurantCode ?? ""];
    const stamp = Date.now();
    createTasks(
      codes.map((code) => ({
        id: `n-${stamp}-${code}`,
        restaurantId: code,
        title: text,
        source: viewer.isHq ? "Поставлено управляющей компанией" : "Добавлено директором",
        assignedBy: viewer.isHq ? "hq" : "director",
        createdAt: todayLabel(),
        due: dateIn(days),
        status: "assigned",
      })),
      viewer.isHq ? `Задача поставлена: ${codes.length > 1 ? "всем директорам" : restaurantName(codes[0]!)}` : "Задача добавлена",
    );
    setTitle("");
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2 rounded-[16px] border border-line bg-surface p-3">
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={viewer.isHq ? "Новая задача: например, «Пересчитать сыры к пятнице»" : "Добавить себе задачу"}
        aria-label="Что сделать"
        className="h-10 min-w-[220px] flex-1 rounded-[10px] border border-line-strong px-3 text-sm outline-none focus:border-brand"
      />
      {viewer.isHq && (
        <select
          value={where}
          onChange={(e) => setWhere(e.target.value)}
          aria-label="Кому"
          className="h-10 rounded-[10px] border border-line-strong bg-surface px-2 text-sm outline-none focus:border-brand"
        >
          <option value="all">Всем директорам</option>
          {RESTAURANTS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
        </select>
      )}
      <select
        value={days}
        onChange={(e) => setDays(Number(e.target.value))}
        aria-label="Срок"
        className="h-10 rounded-[10px] border border-line-strong bg-surface px-2 text-sm outline-none focus:border-brand"
      >
        {DUE_PRESETS.map((p) => (
          <option key={p.days} value={p.days}>
            {p.label} · до {dateIn(p.days)}
          </option>
        ))}
      </select>
      <Button type="submit" variant="primary" disabled={!title.trim()}>
        <Plus size={15} /> Поставить
      </Button>
    </form>
  );
}
