import { Link } from "@tanstack/react-router";
import { Camera, Check } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { Button, Card, cx, EmptyState, PageTitle, Pill, QuestionBlock, Reveal, type Tone } from "../ds/primitives";
import { plural } from "../lib/format";
import { useViewer } from "../lib/useViewer";
import { RESTAURANTS } from "../mock/data";
import { findingById } from "../mock/selectors";
import type { Task } from "../mock/types";
import { usePrototype } from "../state/prototype";
import { useTasks } from "./counts";

const STATUS: Record<Task["status"], { label: string; tone: Tone }> = {
  assigned: { label: "Новая", tone: "neutral" },
  in_progress: { label: "В работе", tone: "info" },
  done: { label: "Сделано", tone: "gain" },
  overdue: { label: "Просрочена", tone: "loss" },
};

function TaskCard({ task, canExecute, showRestaurant }: { task: Task; canExecute: boolean; showRestaurant: boolean }) {
  const { setTaskStatus, toggleCheck, taskChecks, taskReports } = usePrototype();
  const [reporting, setReporting] = useState(false);
  const [report, setReport] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const finding = task.findingId ? findingById(task.findingId) : undefined;
  const checks = taskChecks[task.id] ?? [];
  const steps = task.checklist ?? [];
  const progress = steps.length ? checks.filter(Boolean).length / steps.length : task.status === "done" ? 1 : 0;

  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="font-semibold text-ink">{task.title}</div>
            <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-ink-3">
              {showRestaurant && <span>{RESTAURANTS.find((r) => r.code === task.restaurantId)?.name}</span>}
              <span>Срок {task.due}</span>
              <span>{task.source}</span>
            </div>
          </div>
          <Pill tone={STATUS[task.status].tone}>{STATUS[task.status].label}</Pill>
        </div>
        {finding && (
          <Link
            to="/findings/$findingId"
            params={{ findingId: finding.id }}
            className="mt-3 block rounded-[10px] bg-paper px-3 py-2 text-sm text-ink-2 hover:text-ink"
          >
            Зачем: {finding.title}
            {finding.effectRubMonth !== null && <span className="text-ink-3"> — до {Math.round(finding.effectRubMonth / 1000)} тыс ₽ в месяц</span>}
          </Link>
        )}
        {steps.length > 0 && (
          <div className="mt-4">
            <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-ink/10">
              <motion.div className="h-full bg-brand" animate={{ width: `${progress * 100}%` }} transition={{ duration: 0.3 }} />
            </div>
            <ul className="space-y-1.5">
              {steps.map((s, i) => (
                <li key={s}>
                  <button
                    type="button"
                    disabled={!canExecute || task.status === "done"}
                    onClick={() => toggleCheck(task.id, i, steps.length)}
                    className="flex w-full items-center gap-2.5 rounded-[10px] px-2 py-1.5 text-left text-sm hover:bg-paper disabled:hover:bg-transparent"
                  >
                    <span
                      className={cx(
                        "grid h-5 w-5 shrink-0 place-items-center rounded-md border",
                        checks[i] ? "border-brand bg-brand text-white" : "border-line-strong",
                      )}
                    >
                      {checks[i] && <Check size={13} />}
                    </span>
                    <span className={checks[i] ? "text-ink-3 line-through" : ""}>{s}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(task.report || taskReports[task.id]) && (
          <div className="mt-3 rounded-[10px] bg-paper p-3 text-sm text-ink-2">Отчет: {task.report ?? taskReports[task.id]}</div>
        )}
        {task.result && <div className="mt-2 text-sm font-medium text-gain">{task.result}</div>}
        {task.status === "done" && !task.result && (
          <div className="mt-2 text-sm text-ink-3">Результат в рублях покажем после следующей инвентаризации.</div>
        )}
        {canExecute && task.status !== "done" && (
          <div className="mt-4">
            {reporting ? (
              <div className="space-y-2">
                <textarea
                  className="w-full rounded-[10px] border border-line-strong p-3 text-sm outline-none focus:border-brand"
                  rows={2}
                  placeholder="Коротко: что сделано"
                  value={report}
                  onChange={(e) => setReport(e.target.value)}
                  aria-label="Отчет о выполнении"
                />
                <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-2 hover:text-ink">
                  <Camera size={16} /> {photo ? `Фото: ${photo}` : "Приложить фото"}
                  <input
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    onChange={(e) => setPhoto(e.target.files?.[0]?.name ?? null)}
                  />
                </label>
                <div className="flex gap-2">
                  <Button variant="primary" disabled={!report.trim()} onClick={() => setTaskStatus(task.id, "done", report)}>
                    Отметить сделанной
                  </Button>
                  <Button variant="ghost" onClick={() => setReporting(false)}>
                    Отмена
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex gap-2">
                {task.status === "assigned" && <Button onClick={() => setTaskStatus(task.id, "in_progress")}>Начать</Button>}
                <Button variant="primary" onClick={() => setReporting(true)}>
                  Готово
                </Button>
              </div>
            )}
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
  const open = tasks.filter((t) => t.status !== "done");
  const done = tasks.filter((t) => t.status === "done");
  const overdue = open.filter((t) => t.status === "overdue");

  return (
    <div className="mx-auto max-w-[1040px]">
      <PageTitle
        title={viewer.isHq ? "Задачи ресторанов" : "Мои задачи"}
        subtitle={
          overdue.length
            ? `${plural(open.length, ["открытая задача", "открытые задачи", "открытых задач"])}, из них просрочено: ${overdue.length}`
            : `${plural(open.length, ["открытая задача", "открытые задачи", "открытых задач"])}, просрочек нет`
        }
      />
      {viewer.isHq && (
        <Reveal>
          <QuestionBlock question="Кто как выполняет?" className="mb-6">
            <div className="grid gap-4 sm:grid-cols-3">
              {RESTAURANTS.map((r) => {
                const own = tasks.filter((t) => t.restaurantId === r.code);
                const d = own.filter((t) => t.status === "done").length;
                const late = own.filter((t) => t.status === "overdue").length;
                return (
                  <div key={r.code}>
                    <div className="flex justify-between text-sm">
                      <span className="font-medium">{r.name}</span>
                      <span className="num text-ink-3">
                        {d} из {own.length}
                      </span>
                    </div>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/10">
                      <motion.div
                        className="h-full bg-brand"
                        initial={{ width: 0 }}
                        animate={{ width: `${own.length ? (d / own.length) * 100 : 0}%` }}
                        transition={{ duration: 0.6 }}
                      />
                    </div>
                    <div className={cx("mt-1 text-xs", late ? "text-loss" : "text-ink-3")}>
                      {late ? `Просрочено: ${late}` : "Без просрочек"}
                    </div>
                  </div>
                );
              })}
            </div>
          </QuestionBlock>
        </Reveal>
      )}
      <Reveal index={1}>
        <div className="space-y-3">
          {open.length ? (
            [...overdue, ...open.filter((t) => t.status !== "overdue")].map((t) => (
              <TaskCard key={t.id} task={t} canExecute={!viewer.isHq} showRestaurant={viewer.isHq} />
            ))
          ) : (
            <EmptyState title="Открытых задач нет">Возьмите в работу дело из «Моей недели».</EmptyState>
          )}
        </div>
      </Reveal>
      {done.length > 0 && (
        <Reveal index={2}>
          <h2 className="mt-8 mb-3 font-display text-lg font-semibold">Сделано</h2>
          <div className="space-y-3">
            {done.map((t) => (
              <TaskCard key={t.id} task={t} canExecute={false} showRestaurant={viewer.isHq} />
            ))}
          </div>
        </Reveal>
      )}
    </div>
  );
}
