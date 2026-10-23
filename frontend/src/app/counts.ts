import { useViewer } from "../lib/useViewer";
import { EXPERIMENTS, FINDINGS, TASKS } from "../mock/data";
import type { Task } from "../mock/types";
import { usePrototype } from "../state/prototype";

/** All tasks visible to the viewer, including ones created in this session. */
export function useTasks(): Task[] {
  const viewer = useViewer();
  const { extraTasks, experimentStatus, taskStatus } = usePrototype();
  const fromApprovals: Task[] = EXPERIMENTS.filter((e) => experimentStatus[e.id] === "approved").flatMap((e) =>
    e.test.map((code) => ({
      id: `${e.id}-${code}`,
      restaurantId: code,
      title: e.title,
      source: `Проверка «${e.title}»`,
      experimentId: e.id,
      findingId: e.findingId,
      due: "24.11",
      status: "assigned" as const,
    })),
  );
  const all = [...extraTasks, ...fromApprovals, ...TASKS].filter(
    (t) => viewer && (viewer.isHq || t.restaurantId === viewer.restaurantCode),
  );
  return all.map((t) => ({ ...t, status: taskStatus[t.id] ?? t.status }));
}

export function useOpenTaskCount() {
  return useTasks().filter((t) => t.status !== "done").length;
}

/** HQ inbox: experiments to approve, directors' disputes, overdue tasks. */
export function useInbox() {
  const { experimentStatus, resolvedDisputes, findingStatus, disputes, sentDrafts } = usePrototype();
  const tasks = useTasks();
  const experiments = EXPERIMENTS.filter((e) => e.status === "proposed" && !experimentStatus[e.id]);
  const disputed = FINDINGS.filter(
    (f) => (findingStatus[f.id] ?? f.status) === "disputed" && !resolvedDisputes.includes(f.id),
  ).map((f) => ({
    finding: f,
    dispute: f.dispute ?? { by: "Директор", date: "сегодня", ...(disputes[f.id] ?? { reason: "", comment: "" }) },
  }));
  const overdue = tasks.filter((t) => t.status === "overdue");
  return { experiments, disputed, overdue, drafts: sentDrafts };
}

export function useInboxCount() {
  const { experiments, disputed, overdue, drafts } = useInbox();
  return experiments.length + disputed.length + overdue.length + drafts.length;
}
