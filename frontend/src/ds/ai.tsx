import { Calculator, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useState } from "react";

import { useUi } from "../state/ui";
import { cx, EASE } from "./primitives";

/**
 * Marks text written by the language model. Opens "Почему я это вижу": basis, period, sources.
 * Numbers computed by code are never marked with it (see VerifiedNote).
 */
export function AiBadge({ basis }: { basis: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-full bg-ink px-2 py-0.5 text-[11px] font-semibold text-white"
      >
        <Sparkles size={11} className="text-spark" aria-hidden /> ИИ
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 z-40 mt-2 w-72 rounded-[14px] border border-line bg-surface p-4 text-sm shadow-[var(--shadow-float)]"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold">Почему я это вижу</span>
              <button type="button" onClick={() => setOpen(false)} aria-label="Закрыть" className="text-ink-3 hover:text-ink">
                <X size={14} />
              </button>
            </div>
            <div className="text-ink-2">{basis}</div>
            <div className="mt-2 text-xs text-ink-3">
              Текст сформулировал ИИ. Все цифры в нем посчитаны системой по вашим данным и проверены.
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  );
}

type Confidence = "high" | "medium" | "low";

const CONFIDENCE_WORD: Record<Confidence, string> = { high: "Уверены", medium: "Уверены средне", low: "Пока предположение" };

/** Confidence as a word plus the reason, never a bare percentage. */
export function ConfidenceNote({ confidence, reason }: { confidence: Confidence; reason: string }) {
  const dots = { high: 3, medium: 2, low: 1 }[confidence];
  return (
    <span className="inline-flex items-start gap-2 text-sm">
      <span className="mt-1.5 flex gap-0.5" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={cx("h-1.5 w-3 rounded-full", i <= dots ? "bg-brand" : "bg-ink/15")} />
        ))}
      </span>
      <span>
        <span className="font-medium text-ink">{CONFIDENCE_WORD[confidence]}</span>
        <span className="text-ink-3"> — {reason.charAt(0).toLowerCase() + reason.slice(1)}</span>
      </span>
    </span>
  );
}

/** Footer for computed numbers: period and sources. */
export function VerifiedNote({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Calculator size={12} aria-hidden />
      Посчитано по данным: {children}
    </span>
  );
}

/** Bottom toast with an optional "Отменить". */
export function ToastHost() {
  const { toast, dismissToast } = useUi();
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex justify-center px-4 lg:bottom-8">
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            role="status"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="pointer-events-auto flex items-center gap-4 rounded-full bg-ink py-2.5 pr-2.5 pl-5 text-sm text-white shadow-[var(--shadow-float)]"
          >
            {toast.text}
            {toast.undo && (
              <button
                type="button"
                onClick={() => {
                  toast.undo?.();
                  dismissToast();
                }}
                className="rounded-full bg-white/10 px-3 py-1 font-medium hover:bg-white/20"
              >
                Отменить
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
