import { todayLabel } from "../lib/dates";
import { useViewer } from "../lib/useViewer";
import { EXPERIMENTS, PERIOD, TASKS } from "../mock/data";
import type { Task } from "../mock/types";
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
