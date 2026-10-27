import { CalendarDays, ChevronDown } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { Button, cx, EASE } from "../ds/primitives";
import { TODAY } from "../lib/dates";
import { customRangeError, iso, PRESETS, resolvePeriod } from "../lib/period";
import { useUi } from "../state/ui";

/** Date filter for every screen: presets by full weeks or a custom range (same rules as the API). */
export function PeriodPicker() {
  const { period, setPeriod } = useUi();
  const [open, setOpen] = useState(false);
  const current = resolvePeriod(period);
  const [from, setFrom] = useState(iso(current.from));
  const [to, setTo] = useState(iso(current.to));
  const box = useRef<HTMLDivElement>(null);
  const error = customRangeError(from, to);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="inline-flex h-9 items-center gap-2 rounded-full border border-line-strong bg-surface px-3 text-sm font-medium text-ink transition hover:border-brand"
      >
        <CalendarDays size={15} className="text-ink-3" />
        <span className="sm:hidden">{current.label.split(" · ")[1]}</span>
        <span className="hidden sm:inline">{current.label}</span>
        <ChevronDown size={14} className={cx("text-ink-3 transition", open && "rotate-180")} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Период"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15, ease: EASE }}
            className="absolute top-11 left-0 z-30 w-[300px] rounded-[16px] border border-line bg-surface p-3 shadow-lg"
          >
            <div className="grid gap-1">
              {PRESETS.map((p) => {
                const r = resolvePeriod({ preset: p.preset });
                const active = "preset" in period && period.preset === p.preset;
                return (
                  <button
                    key={p.preset}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setPeriod({ preset: p.preset });
                      setOpen(false);
                    }}
                    className={cx(
                      "flex items-center justify-between rounded-[10px] px-3 py-2 text-left text-sm",
                      active ? "bg-brand-soft font-medium text-brand-strong" : "hover:bg-paper",
                    )}
                  >
                    {p.title}
                    <span className="text-xs text-ink-3">{r.label.split(" · ")[1]}</span>
                  </button>
                );
              })}
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <div className="mb-2 text-xs font-medium text-ink-3">Свой период</div>
              <div className="flex items-center gap-2">
                <input type="date" value={from} max={iso(TODAY)} onChange={(e) => setFrom(e.target.value)} aria-label="С" className="h-9 min-w-0 flex-1 rounded-[8px] border border-line-strong px-2 text-sm outline-none focus:border-brand" />
                <span className="text-ink-3">—</span>
                <input type="date" value={to} max={iso(TODAY)} onChange={(e) => setTo(e.target.value)} aria-label="По" className="h-9 min-w-0 flex-1 rounded-[8px] border border-line-strong px-2 text-sm outline-none focus:border-brand" />
              </div>
              {error && from && to && <div className="mt-1.5 text-xs text-loss">{error}</div>}
              <Button
                variant="primary"
                size="sm"
                className="mt-2 w-full"
                disabled={!!error}
                onClick={() => {
                  setPeriod({ from, to });
                  setOpen(false);
                }}
              >
                Показать
              </Button>
            </div>
            <p className="mt-3 text-[11px] leading-snug text-ink-3">
              Потери по техкартам считаются между инвентаризациями — экран покажет, за какие даты. В прототипе суммы находок
              рассчитаны по данным на 18.10; меняются графики динамики.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
