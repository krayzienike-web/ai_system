// In-memory state for prototype interactions. Resets on reload by design: the prototype has no backend for actions.
import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

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
  disputes: Record<string, { reason: string; comment: string }>;
  taskStatus: Record<string, Task["status"]>;
  taskChecks: Record<string, boolean[]>;
  taskReports: Record<string, string>;
  extraTasks: Task[];
  experimentStatus: Record<string, "approved" | "rejected">;
  sentDrafts: string[]; // finding ids whose experiment draft went to approval
  resolvedDisputes: string[];
  rollouts: string[];
  chat: { open: boolean; context: ChatContextRef | null };
  toast: Toast | null;
}

interface Api extends State {
  takeToWork: (findingId: string, task: Task) => void;
  dispute: (findingId: string, reason: string, comment: string) => void;
  setTaskStatus: (taskId: string, status: Task["status"], report?: string) => void;
  toggleCheck: (taskId: string, index: number, size: number) => void;
  decideExperiment: (id: string, decision: "approved" | "rejected") => void;
  sendDraft: (findingId: string) => void;
  resolveDispute: (findingId: string) => void;
  proposeRollout: (experimentId: string) => void;
  openChat: (context?: ChatContextRef) => void;
  closeChat: () => void;
  notify: (text: string, undo?: () => void) => void;
  dismissToast: () => void;
}

const Ctx = createContext<Api | null>(null);

export function PrototypeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({
    findingStatus: {},
    disputes: {},
    taskStatus: {},
    taskChecks: {},
    taskReports: {},
    extraTasks: [],
    experimentStatus: {},
    sentDrafts: [],
    resolvedDisputes: [],
    rollouts: [],
    chat: { open: false, context: null },
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
      takeToWork: (findingId, task) => {
        patch((s) => ({
          findingStatus: { ...s.findingStatus, [findingId]: "in_work" },
          extraTasks: [task, ...s.extraTasks.filter((t) => t.id !== task.id)],
        }));
        notify("Задача добавлена в «Задачи»", () =>
          patch((s) => {
            const findingStatus = { ...s.findingStatus };
            delete findingStatus[findingId];
            return { findingStatus, extraTasks: s.extraTasks.filter((t) => t.id !== task.id) };
          }),
        );
      },
      dispute: (findingId, reason, comment) => {
        patch((s) => ({
          findingStatus: { ...s.findingStatus, [findingId]: "disputed" },
          disputes: { ...s.disputes, [findingId]: { reason, comment } },
        }));
        notify("Отправлено в управляющую компанию");
      },
      setTaskStatus: (taskId, status, report) => {
        patch((s) => ({
          taskStatus: { ...s.taskStatus, [taskId]: status },
          taskReports: report ? { ...s.taskReports, [taskId]: report } : s.taskReports,
        }));
        if (status === "done") notify("Задача выполнена. Результат посчитаем после следующей инвентаризации");
      },
      toggleCheck: (taskId, index, size) =>
        patch((s) => {
          const checks = [...(s.taskChecks[taskId] ?? Array<boolean>(size).fill(false))];
          checks[index] = !checks[index];
          return { taskChecks: { ...s.taskChecks, [taskId]: checks } };
        }),
      decideExperiment: (id, decision) => {
        patch((s) => ({ experimentStatus: { ...s.experimentStatus, [id]: decision } }));
        notify(decision === "approved" ? "Проверка утверждена, задачи отправлены директорам" : "Проверка отклонена");
      },
      sendDraft: (findingId) => {
        patch((s) => ({ sentDrafts: [...s.sentDrafts, findingId] }));
        notify("Проверка отправлена на утверждение");
      },
      resolveDispute: (findingId) => {
        patch((s) => ({ resolvedDisputes: [...s.resolvedDisputes, findingId] }));
        notify("Спор закрыт, директор увидит ответ");
      },
      proposeRollout: (experimentId) => {
        patch((s) => ({ rollouts: [...s.rollouts, experimentId] }));
        notify("Тиражирование отправлено на утверждение");
      },
      openChat: (context) => patch(() => ({ chat: { open: true, context: context ?? null } })),
      closeChat: () => patch((s) => ({ chat: { ...s.chat, open: false } })),
      notify,
      dismissToast: () => patch(() => ({ toast: null })),
    };
  }, [state, notify]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function usePrototype() {
  const api = useContext(Ctx);
  if (!api) throw new Error("usePrototype outside PrototypeProvider");
  return api;
}
