import { daysUntil, todayLabel } from "../lib/dates";
import { perMonth } from "../lib/format";
import { resolvePeriod } from "../lib/period";
import { useViewer } from "../lib/useViewer";
import { EXPERIMENTS, PERIOD, TASKS } from "../mock/data";
import type { Experiment, Finding, Task } from "../mock/types";
import { usePrototype } from "../state/prototype";

/** All tasks visible to the viewer, including ones created in this session. */
export function useTasks(): Task[] {
  const viewer = useViewer();
  const { extraTasks, experimentStatus, taskStatus, taskReports } = usePrototype();
  const fromApprovals: Task[] = EXPERIMENTS.filter((e) => experimentStatus[e.id] === "approved").flatMap((e) =>
    e.test.map((code) => ({
      id: `${e.id}-${code}`,
      restaurantId: code,
      title: e.title,
      source: `Проверка «${e.title}»`,
      experimentId: e.id,
      findingId: e.findingId,
      assignedBy: "hq" as const,
      createdAt: todayLabel(),
      due: "24.11",
      status: "assigned" as const,
    })),
  );
  const all = [...extraTasks, ...fromApprovals, ...TASKS].filter(
    (t) => viewer && (viewer.isHq || t.restaurantId === viewer.restaurantCode),
  );
  return all.map((t) => {
    const status = taskStatus[t.id] ?? t.status;
    if (status !== "done" || t.status === "done") return { ...t, status };
    // Done in this session: the report is in, the money is measured after the next recount.
    return {
      ...t,
      status,
      doneAt: todayLabel(),
      report: taskReports[t.id],
      outcome: { verdict: "pending" as const, text: `Сколько это дало, посчитаем после инвентаризации ${PERIOD.nextInventory.slice(0, 5)}.` },
    };
  });
}

export function useOpenTaskCount() {
  return useTasks().filter((t) => t.status !== "done").length;
}

/** HQ inbox: experiments to approve, drafts from the team, overdue tasks. */
export function useInbox() {
  const { experimentStatus, sentDrafts } = usePrototype();
  const tasks = useTasks();
  const experiments = EXPERIMENTS.filter((e) => e.status === "proposed" && !experimentStatus[e.id]);
  const overdue = tasks.filter((t) => t.status === "overdue");
  return { experiments, overdue, drafts: sentDrafts };
}

export function useInboxCount() {
  const { experiments, overdue, drafts } = useInbox();
  return experiments.length + overdue.length + drafts.length;
}

export type WorkStage = "new" | "doing" | "checking" | "done";

export interface Work {
  stage: WorkStage;
  tasks: Task[];
  done: number;
  late: number;
  experiment?: Experiment;
  /** One line about the work on a finding, or null when nothing is going on. */
  line: { text: string; tone: "loss" | "gain" | "info" | "warn" } | null;
}

const isLate = (t: Task) => t.status !== "done" && (t.status === "overdue" || daysUntil(t.due) < 0);

/** What is being done about each finding: tasks, the check and the measured result. HQ reads everything from here. */
export function useWork(): (f: Finding) => Work {
  const tasks = useTasks();
  const { findingStatus, experimentStatus } = usePrototype();
  return (f) => {
    const own = tasks.filter((t) => t.findingId === f.id);
    const done = own.filter((t) => t.status === "done").length;
    const late = own.filter(isLate).length;
    const experiment = EXPERIMENTS.find((e) => e.findingId === f.id && experimentStatus[e.id] !== "rejected");
    const launched = experiment && (experiment.status !== "proposed" || experimentStatus[experiment.id] === "approved");
    const confirmed =
      experiment?.result?.effectRubMonth ??
      own.reduce((acc, t) => acc + (t.outcome?.verdict === "confirmed" ? (t.outcome.effectRubMonth ?? 0) : 0), 0);
    const status = findingStatus[f.id] ?? f.status;

    if (status === "resolved" || confirmed > 0) {
      return { stage: "done", tasks: own, done, late, experiment, line: { text: confirmed ? `Сработало: +${perMonth(confirmed)}` : "Есть результат", tone: "gain" } };
    }
    if (launched) {
      return {
        stage: "checking",
        tasks: own,
        done,
        late,
        experiment,
        line: { text: `Идет проверка «${experiment.title}» · ${experiment.period}`, tone: late ? "loss" : "info" },
      };
    }
    if (own.length || status !== "new") {
      const text = own.length ? `Задачи: сделано ${done} из ${own.length}${late ? ` · просрочено ${late}` : ""}` : "В работе";
      return { stage: "doing", tasks: own, done, late, experiment, line: { text, tone: late ? "loss" : "info" } };
    }
    return {
      stage: "new",
      tasks: own,
      done,
      late,
      experiment,
      line: experiment ? { text: "Проверка ждет запуска", tone: "warn" } : null,
    };
  };
}

/** The reporting period chosen in the header, resolved to dates. */
export function usePeriod() {
  const { period } = usePrototype();
  return resolvePeriod(period);
}
