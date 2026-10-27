import { CalendarDays, ChevronDown } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { useAppContext } from "../api/hooks";
import { Button, cx, EASE } from "../ds/primitives";
import { dayMonth } from "../lib/format";
import { useUi } from "../state/ui";

/** Date filter for every screen: presets by full weeks or a custom range (same rules as the API). */
export function PeriodPicker() {
  const { period, setPeriod } = useUi();
  const context = useAppContext();
  const [open, setOpen] = useState(false);
  const presets = context.data?.periods ?? [];
  const today = context.data?.today ?? "";
  // The presets and their dates come from the API (the same rules as every report).
  const preset = "preset" in period ? presets.find((p) => p.preset === period.preset) : undefined;
  const range = preset ? [preset.date_from, preset.date_to] : "from" in period ? [period.from, period.to] : ["", ""];
  const label = `${preset?.title ?? "Период"} · ${dayMonth(range[0])} – ${dayMonth(range[1])}`;
  const [from, setFrom] = useState(range[0] ?? "");
  const [to, setTo] = useState(range[1] ?? "");
  const box = useRef<HTMLDivElement>(null);
  // Only what the form needs to be sendable; the API checks the range itself.
  const error = !from || !to ? "Укажите обе даты" : from > to ? "Начало позже конца" : null;

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
        <span className="sm:hidden">{label.split(" · ")[1]}</span>
        <span className="hidden sm:inline">{label}</span>
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
              {presets.map((p) => {
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
                    <span className="text-xs text-ink-3">
                      {dayMonth(p.date_from)} – {dayMonth(p.date_to)}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <div className="mb-2 text-xs font-medium text-ink-3">Свой период</div>
              <div className="flex items-center gap-2">
                <input type="date" value={from} max={today} onChange={(e) => setFrom(e.target.value)} aria-label="С" className="h-9 min-w-0 flex-1 rounded-[8px] border border-line-strong px-2 text-sm outline-none focus:border-brand" />
                <span className="text-ink-3">—</span>
                <input type="date" value={to} max={today} onChange={(e) => setTo(e.target.value)} aria-label="По" className="h-9 min-w-0 flex-1 rounded-[8px] border border-line-strong px-2 text-sm outline-none focus:border-brand" />
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
              Период меняет динамику и отчет. Суммы находок — на последние данные; потери по техкартам считаются между
              инвентаризациями, экран покажет, за какие даты.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
