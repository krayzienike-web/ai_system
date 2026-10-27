// Interface state only: the chat panel, the period chosen in the header, the toast. Everything the screens show
// comes from the API (ADR 0007); nothing here computes figures or decides anything.
import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

import type { PeriodPreset } from "../api/schema";

export type { PeriodPreset };
export type PeriodChoice = { preset: PeriodPreset } | { from: string; to: string }; // ISO dates

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
  chat: { open: boolean; context: ChatContextRef | null };
  period: PeriodChoice;
  toast: Toast | null;
}

interface Api extends State {
  openChat: (context?: ChatContextRef) => void;
  closeChat: () => void;
  notify: (text: string, undo?: () => void) => void;
  dismissToast: () => void;
  setPeriod: (period: PeriodChoice) => void;
}

const Ctx = createContext<Api | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({
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

  const api = useMemo<Api>(
    () => ({
      ...state,
      openChat: (context) => setState((s) => ({ ...s, chat: { open: true, context: context ?? null } })),
      closeChat: () => setState((s) => ({ ...s, chat: { ...s.chat, open: false } })),
      notify,
      dismissToast: () => setState((s) => ({ ...s, toast: null })),
      setPeriod: (period) => setState((s) => ({ ...s, period })),
    }),
    [state, notify],
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useUi() {
  const api = useContext(Ctx);
  if (!api) throw new Error("useUi outside UiProvider");
  return api;
}
