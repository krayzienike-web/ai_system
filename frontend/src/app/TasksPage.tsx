import { Link } from "@tanstack/react-router";
import { BellRing, Camera, Check, ChevronDown, Search } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { Button, Card, cx, EmptyState, PageTitle, Reveal } from "../ds/primitives";
import { daysUntil } from "../lib/dates";
import { plural, rub } from "../lib/format";
import { useViewer } from "../lib/useViewer";
import { RESTAURANTS } from "../mock/data";
import { findingById } from "../mock/selectors";
import type { Task } from "../mock/types";
import { usePrototype } from "../state/prototype";
import { useTasks } from "./counts";
import { OutcomePill, QuickTaskForm, TaskTrace } from "./tasks/trace";

/** "просрочено на 3 дня" / "сегодня" / "через 8 дней" — when, in words. */
function dueWords(t: Task) {
  if (t.status === "done") return "сделано";
  const days = daysUntil(t.due);
  if (days < 0) return `просрочено на ${plural(-days, ["день", "дня", "дней"])}`;
  if (days === 0) return "срок сегодня";
  return `до ${t.due} · ${plural(days, ["день", "дня", "дней"])}`;
}

const isLate = (t: Task) => t.status !== "done" && (t.status === "overdue" || daysUntil(t.due) < 0);

const STATUS_DOT: Record<Task["status"], string> = {
  assigned: "bg-ink-3",
  in_progress: "bg-info",
  done: "bg-gain-icon",
  overdue: "bg-loss-icon",
};

const restaurantName = (code: string) => RESTAURANTS.find((r) => r.code === code)?.name ?? code;

// ------------------------------------------------------------------ HQ

type Tab = "late" | "open" | "done";

function HqTasks({ tasks }: { tasks: Task[] }) {
  const { notify } = usePrototype();
  const [tab, setTab] = useState<Tab>(tasks.some(isLate) ? "late" : "open");
  const [query, setQuery] = useState("");
  const late = tasks.filter(isLate);
  const open = tasks.filter((t) => t.status !== "done" && !isLate(t));
  const done = tasks.filter((t) => t.status === "done");
  const lists: Record<Tab, Task[]> = { late, open, done };
  const confirmed = done.reduce((acc, t) => acc + (t.outcome?.verdict === "confirmed" ? (t.outcome.effectRubMonth ?? 0) : 0), 0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const perRestaurant = RESTAURANTS.map((r) => {
    const own = tasks.filter((t) => t.restaurantId === r.code);
    return {
      code: r.code,
      name: r.name,
      total: own.length,
      late: own.filter(isLate).length,
      open: own.filter((t) => t.status !== "done").length,
      done: own.filter((t) => t.status === "done").length,
    };
  })
    .filter((r) => r.name.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => b.late - a.late || b.open - a.open);

  const tabs: { key: Tab; label: string }[] = [
    { key: "late", label: "Просрочены" },
    { key: "open", label: "В работе" },
    { key: "done", label: "Сделаны" },
  ];

  return (
    <div className="space-y-6">
      <Reveal>
        <QuickTaskForm />
      </Reveal>
      <Reveal>
        <div className="grid gap-3 sm:grid-cols-3">
          <Card className="p-5">
            <div className="text-sm text-ink-3">Просрочено</div>
            <div className={cx("num mt-1 font-display text-3xl font-semibold", late.length ? "text-loss" : "text-gain")}>{late.length}</div>
            <div className="mt-1 text-xs text-ink-3">{late.length ? "нужно напомнить директорам" : "все в срок"}</div>
          </Card>
          <Card className="p-5">
            <div className="text-sm text-ink-3">В работе</div>
            <div className="num mt-1 font-display text-3xl font-semibold">{open.length}</div>
            <div className="mt-1 text-xs text-ink-3">срок еще не наступил</div>
          </Card>
          <Card className="p-5">
            <div className="text-sm text-ink-3">Сделано</div>
            <div className="num mt-1 font-display text-3xl font-semibold text-gain">{done.length}</div>
            <div className="mt-1 text-xs text-ink-3">
              {confirmed ? `подтверждено +${rub(confirmed)} в месяц` : "результат считаем после инвентаризации"}
            </div>
          </Card>
        </div>
      </Reveal>

      <Reveal index={1}>
        <Card className="p-2">
          <div className="flex flex-wrap items-center justify-between gap-3 px-3 pt-3 pb-2">
            <div className="flex rounded-[10px] border border-line-strong p-0.5" role="tablist">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => setTab(t.key)}
                  className={cx("relative h-9 rounded-[8px] px-3.5 text-sm", tab === t.key ? "text-white" : "text-ink-2 hover:text-ink")}
                >
                  {tab === t.key && (
                    <motion.span layoutId="task-tab" className="absolute inset-0 rounded-[8px] bg-ink" transition={{ type: "spring", stiffness: 500, damping: 36 }} />
                  )}
                  <span className="relative">
                    {t.label} <span className="num opacity-60">{lists[t.key].length}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
          {lists[tab].length ? (
            <ul className="divide-y divide-line">
              {lists[tab].map((t) => {
                const f = t.findingId ? findingById(t.findingId) : undefined;
                const isOpen = expanded === t.id;
                return (
                  <li key={t.id} className="grid grid-cols-[10px_1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3.5">
                    <span className={cx("h-2.5 w-2.5 rounded-full", isLate(t) ? STATUS_DOT.overdue : STATUS_DOT[t.status])} aria-hidden />
                    <span className="min-w-0">
                      <span className="block font-medium text-ink">{t.title}</span>
                      <span className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-3">
                        <span className="font-medium text-ink-2">{restaurantName(t.restaurantId)}</span>
                        <span className={isLate(t) ? "font-medium text-loss" : ""}>{dueWords(t)}</span>
                        {f?.effectRubMonth != null && <span>на кону {rub(f.effectRubMonth)} в месяц</span>}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      {t.status === "done" && <OutcomePill outcome={t.outcome} />}
                      {isLate(t) && (
                        <Button size="sm" onClick={() => notify(`Напоминание отправлено: ${restaurantName(t.restaurantId)}`)}>
                          <BellRing size={14} /> Напомнить
                        </Button>
                      )}
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : t.id)}
                        aria-expanded={isOpen}
                        aria-label="История задачи"
                        className="grid h-8 w-8 place-items-center rounded-[8px] text-ink-3 hover:bg-paper hover:text-ink"
                      >
                        <ChevronDown size={17} className={cx("transition", isOpen && "rotate-180")} />
                      </button>
                    </span>
                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="col-start-2 col-end-4 overflow-hidden"
                        >
                          <div className="pt-3 pb-1">
                            <TaskTrace task={t} />
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="px-4 py-8 text-center text-sm text-ink-3">{tab === "late" ? "Просроченных задач нет." : "Здесь пусто."}</div>
          )}
        </Card>
      </Reveal>

      <Reveal index={2}>
        <Card className="p-2">
          <div className="flex flex-wrap items-center justify-between gap-3 px-3 pt-3 pb-2">
            <div>
              <h2 className="font-display text-base font-semibold">Исполнение по ресторанам</h2>
              <div className="text-xs text-ink-3">Сначала те, у кого есть просрочки</div>
            </div>
            <label className="flex h-9 items-center gap-2 rounded-[10px] border border-line-strong px-3 text-sm focus-within:border-brand">
              <Search size={14} className="text-ink-3" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти ресторан" aria-label="Найти ресторан" className="w-40 outline-none" />
            </label>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr>
                  <th className="px-4 py-2 font-medium">Ресторан</th>
                  <th className="px-4 py-2 text-right font-medium">Просрочено</th>
                  <th className="px-4 py-2 text-right font-medium">В работе</th>
                  <th className="px-4 py-2 text-right font-medium">Сделано</th>
                  <th className="w-[30%] px-4 py-2 font-medium">Выполнено</th>
                </tr>
              </thead>
              <tbody className="num">
                {perRestaurant.map((r) => (
                  <tr key={r.code} className="border-t border-line">
                    <td className="px-4 py-3 font-medium">{r.name}</td>
                    <td className={cx("px-4 py-3 text-right", r.late ? "font-semibold text-loss" : "text-ink-3")}>{r.late || "—"}</td>
                    <td className="px-4 py-3 text-right">{r.open - r.late}</td>
                    <td className="px-4 py-3 text-right">{r.done}</td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-2">
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink/10">
                          <span className="block h-full rounded-full bg-brand" style={{ width: `${r.total ? (r.done / r.total) * 100 : 0}%` }} />
                        </span>
                        <span className="w-9 text-right text-xs text-ink-3">{r.total ? Math.round((r.done / r.total) * 100) : 0}%</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Reveal>
    </div>
  );
}

// ------------------------------------------------------------------ director

function TaskCard({ task }: { task: Task }) {
  const { setTaskStatus, toggleCheck, taskChecks } = usePrototype();
  const [reporting, setReporting] = useState(false);
  const [report, setReport] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const finding = task.findingId ? findingById(task.findingId) : undefined;
  const checks = taskChecks[task.id] ?? [];
  const steps = task.checklist ?? [];
  const late = isLate(task);
  const done = task.status === "done";

  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card className={cx("overflow-hidden", late && "border-loss-icon/50")}>
        <div className="flex flex-wrap items-start justify-between gap-3 p-5 pb-4">
          <div className="min-w-0">
            <div className={cx("text-xs font-semibold uppercase tracking-[0.06em]", late ? "text-loss" : done ? "text-gain" : "text-ink-3")}>
              {dueWords(task)}
            </div>
            <div className="mt-1 text-[17px] font-semibold leading-snug text-ink">{task.title}</div>
          </div>
          {done ? (
            <OutcomePill outcome={task.outcome} />
          ) : finding?.effectRubMonth != null && (
            <div className="text-right">
              <div className="num font-display text-xl font-semibold text-ink">{rub(finding.effectRubMonth)}</div>
              <div className="text-xs text-ink-3">в месяц, если сработает</div>
            </div>
          )}
        </div>

        {steps.length > 0 && (
          <ul className="space-y-1 px-5 pb-4">
            {steps.map((s, i) => (
              <li key={s}>
                <button
                  type="button"
                  disabled={done}
                  onClick={() => toggleCheck(task.id, i, steps.length)}
                  className="flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left text-[15px] hover:bg-paper disabled:hover:bg-transparent"
                >
                  <span className={cx("grid h-5 w-5 shrink-0 place-items-center rounded-md border", checks[i] ? "border-brand bg-brand text-white" : "border-line-strong")}>
                    {checks[i] && <Check size={13} />}
                  </span>
                  <span className={checks[i] ? "text-ink-3 line-through" : ""}>{s}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {done && (
          <div className="mx-5 mb-4 rounded-[14px] bg-paper/70 p-4">
            <TaskTrace task={task} showFinding={false} />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-line bg-paper/50 px-5 py-3">
          {finding && (
            <Link to="/findings/$findingId" params={{ findingId: finding.id }} className="mr-auto text-sm text-ink-3 hover:text-ink">
              Зачем: {finding.title} →
            </Link>
          )}
          {!done && !reporting && (
            <>
              {task.status === "assigned" && <Button onClick={() => setTaskStatus(task.id, "in_progress")}>Начать</Button>}
              <Button variant="primary" onClick={() => setReporting(true)}>
                Готово
              </Button>
            </>
          )}
        </div>
        {reporting && (
          <div className="space-y-2 border-t border-line p-5">
            <textarea
              className="w-full rounded-[10px] border border-line-strong p-3 text-sm outline-none focus:border-brand"
              rows={2}
              placeholder="Коротко: что сделано"
              value={report}
              onChange={(e) => setReport(e.target.value)}
              aria-label="Отчет о выполнении"
            />
            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-2 hover:text-ink">
                <Camera size={16} /> {photo ? `Фото: ${photo}` : "Приложить фото"}
                <input type="file" accept="image/*" className="sr-only" onChange={(e) => setPhoto(e.target.files?.[0]?.name ?? null)} />
              </label>
              <span className="ml-auto flex gap-2">
                <Button variant="ghost" onClick={() => setReporting(false)}>
                  Отмена
                </Button>
                <Button variant="primary" disabled={!report.trim()} onClick={() => setTaskStatus(task.id, "done", report)}>
                  Отметить сделанной
                </Button>
              </span>
            </div>
          </div>
        )}
      </Card>
    </motion.div>
  );
}

export function TasksPage() {
  const viewer = useViewer();
  const tasks = useTasks();
  if (!viewer) return null;
  const open = tasks.filter((t) => t.status !== "done").sort((a, b) => daysUntil(a.due) - daysUntil(b.due));
  const done = tasks.filter((t) => t.status === "done");
  const late = open.filter(isLate);

  return (
    <div className="mx-auto max-w-[960px]">
      <PageTitle
        title={viewer.isHq ? "Задачи ресторанов" : "Мои задачи"}
        subtitle={
          viewer.isHq
            ? "Что директора делают по находкам и проверкам, и где нужна ваша помощь"
            : late.length
              ? `${plural(open.length, ["задача", "задачи", "задач"])} в работе, из них просрочено: ${late.length}`
              : `${plural(open.length, ["задача", "задачи", "задач"])} в работе, просрочек нет`
        }
      />
      {viewer.isHq ? (
        <HqTasks tasks={tasks} />
      ) : (
        <>
          <Reveal>
            <QuickTaskForm />
          </Reveal>
          <Reveal>
            <div className="mt-4 space-y-4">
              {open.length ? open.map((t) => <TaskCard key={t.id} task={t} />) : <EmptyState title="Открытых задач нет">Возьмите в работу дело из «Моей недели».</EmptyState>}
            </div>
          </Reveal>
          {done.length > 0 && (
            <Reveal index={1}>
              <h2 className="mt-10 mb-3 font-display text-lg font-semibold">Сделано</h2>
              <div className="space-y-4">
                {done.map((t) => (
                  <TaskCard key={t.id} task={t} />
                ))}
              </div>
            </Reveal>
          )}
        </>
      )}
    </div>
  );
}
