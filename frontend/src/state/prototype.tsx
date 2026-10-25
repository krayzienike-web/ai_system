// In-memory state for prototype interactions. Resets on reload by design: the prototype has no backend for actions.
import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

import type { PeriodChoice } from "../lib/period";
import type { FindingStatus, Task } from "../mock/types";

export interface ChatContextRef {
  title: string;
  findingId?: string;
}

export interface Toast {
  id: number;
  text: string;
  undo?: () => void;
}

interface State {
  findingStatus: Record<string, FindingStatus>;
  taskStatus: Record<string, Task["status"]>;
  taskChecks: Record<string, boolean[]>;
  taskReports: Record<string, string>;
  extraTasks: Task[];
  experimentStatus: Record<string, "approved" | "rejected">;
  sentDrafts: string[]; // finding ids whose experiment draft went to approval
  rollouts: string[];
  chat: { open: boolean; context: ChatContextRef | null };
  period: PeriodChoice;
  toast: Toast | null;
}

interface Api extends State {
  /** Creates tasks (one per restaurant); the finding moves to "Делаем"; the toast offers undo. */
  createTasks: (tasks: Task[], toast?: string) => void;
  setTaskStatus: (taskId: string, status: Task["status"], report?: string) => void;
  toggleCheck: (taskId: string, index: number, size: number) => void;
  decideExperiment: (id: string, decision: "approved" | "rejected") => void;
  sendDraft: (findingId: string) => void;
  proposeRollout: (experimentId: string) => void;
  openChat: (context?: ChatContextRef) => void;
  closeChat: () => void;
  notify: (text: string, undo?: () => void) => void;
  dismissToast: () => void;
  setPeriod: (period: PeriodChoice) => void;
}

const Ctx = createContext<Api | null>(null);

export function PrototypeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({
    findingStatus: {},
    taskStatus: {},
    taskChecks: {},
    taskReports: {},
    extraTasks: [],
    experimentStatus: {},
    sentDrafts: [],
    rollouts: [],
    chat: { open: false, context: null },
    period: { preset: "week" },
    toast: null,
  });
  const toastSeq = useRef(0);

  const notify = useCallback((text: string, undo?: () => void) => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    setState((s) => ({ ...s, toast: { id, text, undo } }));
    window.setTimeout(() => setState((s) => (s.toast?.id === id ? { ...s, toast: null } : s)), 5000);
  }, []);

  const api = useMemo<Api>(() => {
    const patch = (fn: (s: State) => Partial<State>) => setState((s) => ({ ...s, ...fn(s) }));
    return {
      ...state,
      createTasks: (tasks, toast) => {
        const ids = new Set(tasks.map((t) => t.id));
        patch((s) => {
          const findingStatus = { ...s.findingStatus };
          for (const t of tasks) if (t.findingId && !findingStatus[t.findingId]) findingStatus[t.findingId] = "in_work";
          return { findingStatus, extraTasks: [...tasks, ...s.extraTasks.filter((t) => !ids.has(t.id))] };
        });
        notify(toast ?? "Задача добавлена в «Задачи»", () =>
          patch((s) => {
            const extraTasks = s.extraTasks.filter((t) => !ids.has(t.id));
            const findingStatus = { ...s.findingStatus };
            for (const t of tasks) {
              if (t.findingId && !extraTasks.some((x) => x.findingId === t.findingId)) delete findingStatus[t.findingId];
            }
            return { findingStatus, extraTasks };
          }),
        );
      },
      setTaskStatus: (taskId, status, report) => {
        patch((s) => ({
          taskStatus: { ...s.taskStatus, [taskId]: status },
          taskReports: report ? { ...s.taskReports, [taskId]: report } : s.taskReports,
        }));
        if (status === "done") notify("Отчет отправлен. Результат в рублях посчитаем после инвентаризации и покажем у задачи");
      },
      toggleCheck: (taskId, index, size) =>
        patch((s) => {
          const checks = [...(s.taskChecks[taskId] ?? Array<boolean>(size).fill(false))];
          checks[index] = !checks[index];
          return { taskChecks: { ...s.taskChecks, [taskId]: checks } };
        }),
      decideExperiment: (id, decision) => {
        patch((s) => ({ experimentStatus: { ...s.experimentStatus, [id]: decision } }));
        notify(decision === "approved" ? "Проверка запущена, задачи отправлены директорам" : "Проверка отклонена");
      },
      sendDraft: (findingId) => {
        patch((s) => ({ sentDrafts: [...s.sentDrafts, findingId] }));
        notify("Проверка передана на запуск");
      },
      proposeRollout: (experimentId) => {
        patch((s) => ({ rollouts: [...s.rollouts, experimentId] }));
        notify("Тиражирование передано на запуск");
      },
      openChat: (context) => patch(() => ({ chat: { open: true, context: context ?? null } })),
      closeChat: () => patch((s) => ({ chat: { ...s.chat, open: false } })),
      notify,
      dismissToast: () => patch(() => ({ toast: null })),
      setPeriod: (period) => patch(() => ({ period })),
    };
  }, [state, notify]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function usePrototype() {
  const api = useContext(Ctx);
  if (!api) throw new Error("usePrototype outside PrototypeProvider");
  return api;
}
