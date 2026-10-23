import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { Button, Card, EmptyState, PageHeader, Pill, SectionTitle } from "../components/ui";
import { useViewer } from "../lib/useViewer";
import { EXPERIMENTS, RESTAURANTS, TASKS } from "../mock/data";
import type { Task } from "../mock/types";
import { usePrototype } from "../state/prototype";

const STATUS: Record<Task["status"], { label: string; tone: "neutral" | "loss" | "gain" | "info" }> = {
  assigned: { label: "Новая", tone: "neutral" },
  in_progress: { label: "В работе", tone: "info" },
  done: { label: "Выполнена", tone: "gain" },
  overdue: { label: "Просрочена", tone: "loss" },
};

function TaskCard({ task, canExecute, showRestaurant }: { task: Task; canExecute: boolean; showRestaurant: boolean }) {
  const { taskStatus, setTaskStatus } = usePrototype();
  const status = taskStatus[task.id] ?? task.status;
  const [reporting, setReporting] = useState(false);
  const [report, setReport] = useState("");

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="font-medium text-slate-900">{task.title}</div>
        <Pill tone={STATUS[status].tone}>{STATUS[status].label}</Pill>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
        {showRestaurant && <span>{RESTAURANTS.find((r) => r.code === task.restaurantId)?.name}</span>}
        <span>Срок {task.due}</span>
        <span>{task.source}</span>
        {task.findingId && (
          <Link to="/insights/$findingId" params={{ findingId: task.findingId }} className="underline">
            основание
          </Link>
        )}
      </div>
      {task.checklist && (
        <ul className="mt-3 space-y-1 text-sm text-slate-700">
          {task.checklist.map((c) => (
            <li key={c}>
              <label className="flex items-center gap-2">
                <input type="checkbox" disabled={!canExecute} /> {c}
              </label>
            </li>
          ))}
        </ul>
      )}
      {(task.report || (status === "done" && report)) && (
        <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-700">Отчет: {task.report ?? report}</div>
      )}
      {canExecute && status !== "done" && (
        <div className="mt-3">
          {reporting ? (
            <div className="space-y-2">
              <textarea
                className="w-full rounded-md border border-slate-300 p-2 text-sm"
                rows={2}
                placeholder="Что сделано (в рабочей версии — можно приложить фото)"
                value={report}
                onChange={(e) => setReport(e.target.value)}
                aria-label="Отчет о выполнении"
              />
              <div className="flex gap-2">
                <Button variant="primary" disabled={!report.trim()} onClick={() => setTaskStatus(task.id, "done")}>
                  Отметить выполненной
                </Button>
                <Button variant="ghost" onClick={() => setReporting(false)}>
                  Отмена
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              {status === "assigned" && <Button onClick={() => setTaskStatus(task.id, "in_progress")}>Начать</Button>}
              <Button variant="primary" onClick={() => setReporting(true)}>
                Выполнено
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export function TasksPage() {
  const viewer = useViewer();
  const { extraTasks, experimentStatus, taskStatus } = usePrototype();
  if (!viewer) return null;

  // Approving an experiment creates tasks for its test restaurants (prototype simulation).
  const fromApprovals: Task[] = EXPERIMENTS.filter((e) => experimentStatus[e.id] === "approved").flatMap((e) =>
    e.test.map((code) => ({
      id: `${e.id}-${code}`,
      restaurantId: code,
      title: e.title,
      source: `Эксперимент «${e.title}»`,
      experimentId: e.id,
      findingId: e.findingId,
      due: "24.11",
      status: "assigned" as const,
    })),
  );
  const all = [...extraTasks, ...fromApprovals, ...TASKS].filter((t) => viewer.isHq || t.restaurantId === viewer.restaurantCode);
  const isDone = (t: Task) => (taskStatus[t.id] ?? t.status) === "done";
  const open = all.filter((t) => !isDone(t));
  const done = all.filter(isDone);

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title={viewer.isHq ? "Задачи ресторанов" : "Мои задачи"} meta={`${open.length} открытых`} />
      <section className="mb-6 space-y-3">
        {open.length ? (
          open.map((t) => <TaskCard key={t.id} task={t} canExecute={!viewer.isHq} showRestaurant={viewer.isHq} />)
        ) : (
          <EmptyState title="Открытых задач нет">Возьмите в работу пункт из сводки недели.</EmptyState>
        )}
      </section>
      {done.length > 0 && (
        <section className="space-y-3">
          <SectionTitle>Выполненные</SectionTitle>
          {done.map((t) => (
            <TaskCard key={t.id} task={t} canExecute={!viewer.isHq} showRestaurant={viewer.isHq} />
          ))}
        </section>
      )}
    </div>
  );
}
