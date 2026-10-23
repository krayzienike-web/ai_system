// In-memory state for prototype interactions (taking a finding to work, approving an experiment…).
// Resets on reload by design: the prototype has no backend for these actions yet.
import { createContext, type ReactNode, useContext, useMemo, useState } from "react";

import type { FindingStatus, Task } from "../mock/types";

export interface ChatContextRef {
  title: string;
  findingId?: string;
}

interface PrototypeState {
  findingStatus: Record<string, FindingStatus>;
  disputeReasons: Record<string, string>;
  taskStatus: Record<string, Task["status"]>;
  extraTasks: Task[];
  experimentStatus: Record<string, "approved" | "rejected">;
  chat: { open: boolean; context: ChatContextRef | null };
}

interface PrototypeApi extends PrototypeState {
  takeToWork: (findingId: string, task: Task) => void;
  dispute: (findingId: string, reason: string) => void;
  setTaskStatus: (taskId: string, status: Task["status"]) => void;
  decideExperiment: (id: string, decision: "approved" | "rejected") => void;
  openChat: (context?: ChatContextRef) => void;
  closeChat: () => void;
}

const Ctx = createContext<PrototypeApi | null>(null);

export function PrototypeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PrototypeState>({
    findingStatus: {},
    disputeReasons: {},
    taskStatus: {},
    extraTasks: [],
    experimentStatus: {},
    chat: { open: false, context: null },
  });

  const api = useMemo<PrototypeApi>(
    () => ({
      ...state,
      takeToWork: (findingId, task) =>
        setState((s) => ({
          ...s,
          findingStatus: { ...s.findingStatus, [findingId]: "in_work" },
          extraTasks: [task, ...s.extraTasks],
        })),
      dispute: (findingId, reason) =>
        setState((s) => ({
          ...s,
          findingStatus: { ...s.findingStatus, [findingId]: "disputed" },
          disputeReasons: { ...s.disputeReasons, [findingId]: reason },
        })),
      setTaskStatus: (taskId, status) =>
        setState((s) => ({ ...s, taskStatus: { ...s.taskStatus, [taskId]: status } })),
      decideExperiment: (id, decision) =>
        setState((s) => ({ ...s, experimentStatus: { ...s.experimentStatus, [id]: decision } })),
      openChat: (context) => setState((s) => ({ ...s, chat: { open: true, context: context ?? null } })),
      closeChat: () => setState((s) => ({ ...s, chat: { ...s.chat, open: false } })),
    }),
    [state],
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function usePrototype() {
  const api = useContext(Ctx);
  if (!api) throw new Error("usePrototype outside PrototypeProvider");
  return api;
}
