import { Link, Navigate } from "@tanstack/react-router";
import { Camera, Check } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { Button, Card, cx, EmptyState, PageTitle, Reveal } from "../ds/primitives";
import { daysUntil } from "../lib/dates";
import { plural, rub } from "../lib/format";
import { useViewer } from "../lib/useViewer";
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
  // The management company follows work inside each finding; the restaurant lives in its task list.
  if (viewer.isHq) return <Navigate to="/findings" />;
  const open = tasks.filter((t) => t.status !== "done").sort((a, b) => daysUntil(a.due) - daysUntil(b.due));
  const done = tasks.filter((t) => t.status === "done");
  const late = open.filter(isLate);

  return (
    <div className="mx-auto max-w-[960px]">
      <PageTitle
        title="Мои задачи"
        subtitle={
          late.length
            ? `${plural(open.length, ["задача", "задачи", "задач"])} в работе, из них просрочено: ${late.length}`
            : `${plural(open.length, ["задача", "задачи", "задач"])} в работе, просрочек нет`
        }
      />
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
    </div>
  );
}
