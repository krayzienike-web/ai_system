import { Link } from "@tanstack/react-router";
import { Check, CheckCircle2, Clock, Plus, XCircle } from "lucide-react";
import { motion } from "motion/react";
import { type FormEvent, useState } from "react";

import { useAppContext, useCreateTasks, useRestaurants } from "../../api/hooks";
import type { ApiFinding, ApiTask, TaskOutcome } from "../../api/types";
import { Button, cx, EASE, ErrorText } from "../../ds/primitives";
import { ddmm, money, perMonth } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";

/** The measured result of a task in one line: worked (₽) / did not work / not measured yet. */
export function OutcomePill({ outcome }: { outcome?: TaskOutcome | null }) {
  if (!outcome) return null;
  const effect = money(outcome.effect_rub_month);
  if (outcome.verdict === "confirmed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-gain-soft px-2.5 py-1 text-xs font-semibold text-gain">
        <CheckCircle2 size={13} /> Сработало{effect ? `: +${perMonth(effect)}` : ""}
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
 * The result is computed by the system after the recount or the check, never typed by a person.
 */
export function TaskTrace({ task, showFinding = true, showRestaurant = false }: { task: ApiTask; showFinding?: boolean; showRestaurant?: boolean }) {
  const viewer = useViewer();
  const done = task.status === "done";
  const o = task.outcome;

  const steps: { title: string; state: StepState; body: React.ReactNode }[] = [
    {
      title: "Нашли",
      state: "done",
      body:
        task.finding_id && task.finding_title ? (
          showFinding ? (
            <Link to="/findings/$findingId" params={{ findingId: task.finding_id }} className="text-brand-strong hover:underline">
              {task.finding_title}
            </Link>
          ) : (
            <span className="text-ink-2">{task.finding_title}</span>
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
          {ddmm(task.created_on)} · {task.assigned_by === "hq" ? "управляющая компания" : "директор"}
          {showRestaurant && task.restaurant_name && ` → ${task.restaurant_name}`} · срок {ddmm(task.due_on)}
        </span>
      ),
    },
    {
      title: "Выполнили",
      state: done ? "done" : task.late ? "bad" : "current",
      body: done ? (
        <span className="text-ink-2">
          {ddmm(task.done_on)}
          {task.report && <span className="mt-1 block rounded-[10px] bg-paper px-3 py-2 text-ink">«{task.report}»</span>}
        </span>
      ) : (
        <span className={task.late ? "font-medium text-loss" : "text-ink-3"}>
          {task.late ? `Просрочено, срок был ${ddmm(task.due_on)}` : `В работе, срок до ${ddmm(task.due_on)}`}
        </span>
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
            {o.measured_on && <span className="text-ink-3"> · посчитано {ddmm(o.measured_on)}</span>}
          </span>
          {task.experiment_id && viewer?.isHq && (
            <Link to="/checks/$checkId" params={{ checkId: task.experiment_id }} className="inline-block text-brand-strong hover:underline">
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

/** "Что сделать" with a one-click task on every step: HQ assigns it to the director, a director takes it. */
export function QuickSteps({ f, tasks }: { f: ApiFinding; tasks: ApiTask[] }) {
  const viewer = useViewer();
  const create = useCreateTasks();
  const context = useAppContext();
  const { notify } = useUi();
  const [days, setDays] = useState(7);
  if (!viewer) return null;
  const byHq = viewer.isHq;
  const mayCreate = viewer.can(byHq ? "tasks.assign" : "tasks.execute");
  const forWhom = f.restaurant_id ? (byHq ? "директору" : "себе") : "всем директорам";
  const option = context.data?.due_options.find((o) => o.days === days);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Что сделать</span>
        <span className="flex items-center gap-1 text-xs text-ink-3">
          Срок:
          {context.data?.due_options.map((p) => (
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
          const existing = tasks.filter((t) => t.title === a);
          return (
            <li key={a} className="flex flex-wrap items-start gap-3 rounded-[12px] border border-line p-3">
              <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand-strong">{i + 1}</span>
              <span className="min-w-0 flex-1 pt-0.5">{a}</span>
              {existing.length ? (
                byHq ? (
                  <span className="inline-flex items-center gap-1 pt-0.5 text-xs font-medium text-brand-strong">
                    <Check size={13} /> Поставлено до {ddmm(existing[0]!.due_on)}
                    {existing.length > 1 && ` · ${existing.length} рест.`}
                  </span>
                ) : (
                  <Link to="/tasks" className="inline-flex items-center gap-1 pt-0.5 text-xs font-medium text-brand-strong hover:underline">
                    <Check size={13} /> Задача до {ddmm(existing[0]!.due_on)} →
                  </Link>
                )
              ) : !mayCreate ? null : (
                <Button
                  size="sm"
                  disabled={!option || create.isPending}
                  onClick={() =>
                    create.mutate(
                      { title: a, finding_id: f.id, due_on: option!.due_on },
                      {
                        onSuccess: () =>
                          notify(
                            byHq
                              ? `Задача поставлена ${forWhom}, срок ${ddmm(option!.due_on)}`
                              : `Задача в «Моих задачах», срок ${ddmm(option!.due_on)}`,
                          ),
                      },
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
      <ErrorText error={create.error} fallback="Не получилось поставить задачу. Попробуйте еще раз." className="mt-2" />
    </div>
  );
}

/** One-line task creation without a finding: what, where, by when. */
export function QuickTaskForm() {
  const viewer = useViewer();
  const create = useCreateTasks();
  const context = useAppContext();
  const restaurants = useRestaurants();
  const { notify } = useUi();
  const [title, setTitle] = useState("");
  const [where, setWhere] = useState("all");
  const [days, setDays] = useState(7);
  if (!viewer || !viewer.can(viewer.isHq ? "tasks.assign" : "tasks.execute")) return null;
  const option = context.data?.due_options.find((o) => o.days === days);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = title.trim();
    if (!text || !option) return;
    const all = (restaurants.data ?? []).map((r) => r.id);
    create.mutate(
      {
        title: text,
        due_on: option.due_on,
        restaurant_ids: viewer.isHq ? (where === "all" ? all : [where]) : undefined,
      },
      {
        onSuccess: () => {
          notify(viewer.isHq ? (where === "all" ? "Задача поставлена всем директорам" : "Задача поставлена") : "Задача добавлена");
          setTitle("");
        },
      },
    );
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
          {(restaurants.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
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
        {context.data?.due_options.map((p) => (
          <option key={p.days} value={p.days}>
            {p.label} · до {ddmm(p.due_on)}
          </option>
        ))}
      </select>
      <Button type="submit" variant="primary" disabled={!title.trim() || !option || create.isPending}>
        <Plus size={15} /> Поставить
      </Button>
      <ErrorText error={create.error} fallback="Не получилось поставить задачу. Попробуйте еще раз." className="w-full" />
    </form>
  );
}
