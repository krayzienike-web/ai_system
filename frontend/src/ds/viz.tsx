import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarClock,
  Check,
  ChefHat,
  ClipboardList,
  Database,
  type LucideIcon,
  PackageCheck,
  Refrigerator,
  ShoppingCart,
  Trash2,
} from "lucide-react";
import { animate, motion, useReducedMotion } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";

import type { ProcessKey, Status } from "../mock/types";
import { cx, EASE } from "./primitives";

// ------------------------------------------------------------------ animated numbers

/** Counts up to `value` (600 ms); renders the final value at once with reduced motion. */
export function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const controls = animate(0, value, { duration: 0.6, ease: EASE, onUpdate: setShown });
    return () => controls.stop();
  }, [value, reduce]);
  return <span className="num">{format(Math.round(reduce ? value : shown))}</span>;
}

// ------------------------------------------------------------------ bullet scale

export interface BulletScaleProps {
  /** Values in one unit; `lowerIsBetter` decides which side of the norm is the bad zone. */
  me: number;
  network?: number;
  norm?: number;
  lowerIsBetter?: boolean;
  max?: number;
  format: (n: number) => string;
  meLabel?: string;
  networkLabel?: string;
}

/**
 * One scale for "me / network / norm" instead of three numbers in a row.
 * The track is tinted: green up to the norm, red beyond it (or the reverse when higher is better).
 */
export function BulletScale({ me, network, norm, lowerIsBetter = true, max, format, meLabel = "Вы", networkLabel = "Сеть" }: BulletScaleProps) {
  const top = max ?? Math.max(me, network ?? 0, norm ?? 0) * 1.25;
  const x = (v: number) => `${Math.min(100, (v / top) * 100)}%`;
  const bad = norm !== undefined && (lowerIsBetter ? me > norm : me < norm);
  return (
    <div className="pt-6 pb-7">
      <div className="relative h-3 rounded-full bg-ink/5">
        {norm !== undefined && (
          <>
            <div
              className={cx("absolute inset-y-0 left-0 rounded-l-full", lowerIsBetter ? "bg-gain-soft" : "bg-loss-soft")}
              style={{ width: x(norm) }}
            />
            <div
              className={cx("absolute inset-y-0 right-0 rounded-r-full", lowerIsBetter ? "bg-loss-soft" : "bg-gain-soft")}
              style={{ left: x(norm) }}
            />
          </>
        )}
        <motion.div
          className={cx("absolute inset-y-0.5 left-0.5 rounded-full", bad ? "bg-loss-icon" : "bg-brand")}
          initial={{ width: 0 }}
          animate={{ width: `calc(${x(me)} - 4px)` }}
          transition={{ duration: 0.6, ease: EASE }}
        />
        {/* me label above */}
        <div className="absolute -top-6 -translate-x-1/2 whitespace-nowrap text-xs font-semibold text-ink" style={{ left: x(me) }}>
          {meLabel} {format(me)}
        </div>
        {network !== undefined && (
          <div className="absolute -top-1 bottom-[-4px] w-0.5 bg-network" style={{ left: x(network) }}>
            <div
              className={cx(
                "absolute top-5 whitespace-nowrap text-[11px] font-medium text-ink-2",
                norm === undefined ? "-translate-x-1/2" : network >= norm ? "pl-1" : "-translate-x-full pr-1",
              )}
            >
              {networkLabel} {format(network)}
            </div>
          </div>
        )}
        {norm !== undefined && (
          <div className="absolute -top-1 bottom-[-4px] border-l-2 border-dashed border-ink" style={{ left: x(norm) }}>
            <div
              className={cx(
                "absolute top-5 whitespace-nowrap text-[11px] text-ink-3",
                network === undefined || network >= norm ? "-translate-x-full pr-1" : "pl-1",
              )}
            >
              Норма {format(norm)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ composition bar

export interface Part {
  label: string;
  value: number;
  tone: "brand" | "neutral" | "loss" | "gain";
}

const PART_COLOR: Record<Part["tone"], string> = {
  brand: "bg-brand",
  neutral: "bg-ink-3",
  loss: "bg-loss-icon",
  gain: "bg-gain-icon",
};

/** One bar = one total split into named parts ("what the used stock consisted of"). */
export function CompositionBar({ parts, format }: { parts: Part[]; format: (n: number) => string }) {
  const total = parts.reduce((acc, p) => acc + p.value, 0);
  return (
    <div>
      <div className="flex h-9 gap-0.5 overflow-hidden rounded-[10px]">
        {parts.map((p, i) => (
          <motion.div
            key={p.label}
            className={cx("h-full first:rounded-l-[10px] last:rounded-r-[10px]", PART_COLOR[p.tone])}
            style={{ minWidth: 6 }}
            initial={{ flexGrow: 0 }}
            animate={{ flexGrow: p.value / total }}
            transition={{ duration: 0.6, ease: EASE, delay: i * 0.1 }}
            title={`${p.label}: ${format(p.value)}`}
          />
        ))}
      </div>
      <ul className="mt-3 grid gap-2 sm:grid-cols-3">
        {parts.map((p) => (
          <li key={p.label} className="flex items-start gap-2 text-sm">
            <span className={cx("mt-1 h-3 w-3 shrink-0 rounded-sm", PART_COLOR[p.tone])} aria-hidden />
            <span>
              <span className={cx("num font-semibold", p.tone === "loss" && "text-loss")}>{format(p.value)}</span>{" "}
              <span className="text-ink-2">{p.label}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ ranking

export interface RankItem {
  id: string;
  title: string;
  value: number;
  valueLabel: string;
  sub?: ReactNode;
  delta?: number; // change vs previous period, same unit as value; positive = worse for losses
  onClick?: () => void;
}

/** Ranked bars: who is ahead and who is behind, with change since last week. */
export function RankList({ items, deltaGoodWhenNegative = true }: { items: RankItem[]; deltaGoodWhenNegative?: boolean }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ol className="space-y-1">
      {items.map((item, i) => {
        const good = item.delta !== undefined && (deltaGoodWhenNegative ? item.delta < 0 : item.delta > 0);
        const Delta = item.delta !== undefined && item.delta < 0 ? ArrowDownRight : ArrowUpRight;
        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={item.onClick}
              disabled={!item.onClick}
              className="group grid w-full grid-cols-[24px_1fr_auto] items-center gap-x-3 gap-y-1.5 rounded-[12px] px-2 py-2.5 text-left transition-colors hover:bg-paper disabled:hover:bg-transparent"
            >
              <span className="num text-sm font-semibold text-ink-3">{i + 1}</span>
              <span className="min-w-0 truncate font-medium text-ink group-hover:underline">{item.title}</span>
              <span className="num text-right font-semibold text-ink">{item.valueLabel}</span>
              <span />
              <span className="h-2 overflow-hidden rounded-full bg-ink/5">
                <motion.span
                  className="block h-full rounded-full bg-loss-icon/80"
                  initial={{ width: 0 }}
                  animate={{ width: `${(item.value / max) * 100}%` }}
                  transition={{ duration: 0.6, ease: EASE, delay: i * 0.06 }}
                />
              </span>
              <span className="text-right text-xs">
                {item.delta !== undefined && item.delta !== 0 && (
                  <span className={cx("inline-flex items-center gap-0.5", good ? "text-gain" : "text-loss")}>
                    <Delta size={12} aria-hidden />
                    {good ? "лучше" : "хуже"}
                  </span>
                )}
              </span>
              {item.sub && (
                <>
                  <span />
                  <span className="col-span-2 text-xs text-ink-3">{item.sub}</span>
                </>
              )}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ improvement cycle

export const CYCLE = ["Нашли", "Делаем", "Проверяем", "Результат"] as const;

/** Where a finding is in the loop "found → doing → checking → result". */
export function CycleSteps({ current, notes }: { current: number; notes?: (string | undefined)[] }) {
  return (
    <ol className="grid grid-cols-4 gap-1" aria-label="Этапы">
      {CYCLE.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={step} className="min-w-0">
            <div className="h-1.5 overflow-hidden rounded-full bg-ink/10">
              <motion.div
                className="h-full bg-brand"
                initial={{ width: 0 }}
                animate={{ width: done ? "100%" : active ? "50%" : "0%" }}
                transition={{ duration: 0.5, ease: EASE, delay: i * 0.15 }}
              />
            </div>
            <div className={cx("mt-1.5 flex items-center gap-1 text-xs", active ? "font-semibold text-ink" : done ? "text-brand-strong" : "text-ink-3")}>
              {done && <Check size={12} aria-hidden />}
              {step}
            </div>
            {notes?.[i] && <div className="truncate text-[11px] text-ink-3">{notes[i]}</div>}
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ process map

export const PROCESS_ICON: Record<ProcessKey, LucideIcon> = {
  purchasing: ShoppingCart,
  receiving: PackageCheck,
  storage: Refrigerator,
  production: ChefHat,
  writeoffs: Trash2,
  inventory: ClipboardList,
  accounting: Database,
  planning: CalendarClock,
};

const STATUS_STYLE: Record<Status, { tile: string; icon: string }> = {
  good: { tile: "border-line bg-surface", icon: "bg-gain-soft text-gain" },
  warning: { tile: "border-warn-icon/40 bg-warn-soft/40", icon: "bg-warn-soft text-warn" },
  critical: { tile: "border-loss-icon/40 bg-loss-soft/50", icon: "bg-loss-soft text-loss" },
};

export interface ProcessTile {
  key: ProcessKey;
  title: string;
  status: Status;
  /** Losses in rubles per month; 0 with a non-good status means a data gap. */
  losses: number;
  detail: string; // "38 тыс ₽ в месяц"
}

export function ProcessMap({
  tiles,
  selected,
  onSelect,
}: {
  tiles: ProcessTile[];
  selected?: ProcessKey | null;
  onSelect?: (key: ProcessKey | null) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {tiles.map((t, i) => {
        const Icon = PROCESS_ICON[t.key];
        const s = STATUS_STYLE[t.status];
        const isSelected = selected === t.key;
        return (
          <motion.button
            key={t.key}
            type="button"
            onClick={() => onSelect?.(isSelected ? null : t.key)}
            aria-pressed={isSelected}
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3, ease: EASE, delay: i * 0.03 }}
            whileHover={{ y: -2 }}
            className={cx(
              "flex min-w-0 flex-col gap-2 rounded-[14px] border p-3 text-left transition-shadow",
              s.tile,
              isSelected && "ring-2 ring-brand",
            )}
          >
            <span className="flex items-center gap-2">
              <span className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-[9px]", s.icon)}>
                <Icon size={17} strokeWidth={1.75} aria-hidden />
              </span>
              <span className="min-w-0 text-sm font-medium leading-tight text-ink">{t.title}</span>
            </span>
            <span className="text-xs">
              <span className={cx("font-semibold", t.status === "critical" ? "text-loss" : t.status === "warning" ? "text-warn" : "text-gain")}>
                {t.status === "good" ? "В норме" : t.losses ? "Теряем" : "Пробел в данных"}
              </span>
              {t.losses > 0 && <span className="num text-ink-2"> · {t.detail}</span>}
            </span>
          </motion.button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ sparkline / area trend

/** Small area chart for a weekly series, with the last point emphasized. Pure SVG, scales to width. */
export function AreaTrend({
  series,
  labels,
  height = 120,
  format,
}: {
  series: { name: string; values: number[]; color: string; fill?: boolean }[];
  labels: string[];
  height?: number;
  format: (n: number) => string;
}) {
  const w = 600;
  const h = height;
  const pad = { t: 10, r: 12, b: 22, l: 12 };
  const values = series.flatMap((s) => s.values);
  const top = Math.max(...values);
  const bottom = Math.min(...values);
  const span = top - bottom || top || 1;
  // Not from zero: the point is the change, so the scale hugs the data with a margin.
  const max = top + span * 0.25;
  const min = Math.max(0, bottom - span * 0.6);
  const n = labels.length;
  const px = (i: number) => pad.l + (i / (n - 1)) * (w - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - (v - min) / (max - min)) * (h - pad.t - pad.b);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-auto w-full" role="img" aria-label={series.map((s) => s.name).join(", ")}>
      {[bottom, top].map((v) => (
        <line key={v} x1={pad.l} x2={w - pad.r} y1={py(v)} y2={py(v)} stroke="#DFE6E3" strokeWidth="1" />
      ))}
      {series.map((s, si) => {
        const d = s.values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
        const last = s.values[s.values.length - 1] ?? 0;
        return (
          <g key={s.name}>
            {s.fill && (
              <motion.path
                d={`${d} L${px(n - 1)},${py(min)} L${px(0)},${py(min)} Z`}
                fill={s.color}
                initial={{ opacity: 0 }}
                animate={{ opacity: 0.12 }}
                transition={{ duration: 0.6, delay: 0.2 + si * 0.1 }}
              />
            )}
            <motion.path
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth="2.5"
              strokeLinejoin="round"
              strokeLinecap="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.9, ease: EASE, delay: si * 0.15 }}
            />
            <text x={px(0)} y={py(s.values[0] ?? 0) - 10} fontSize="12" fill="#3D4A57" fontWeight="600">
              {format(s.values[0] ?? 0)}
            </text>
            <text x={px(n - 1)} y={py(last) - 12} textAnchor="end" fontSize="12" fill="#14202B" fontWeight="700">
              {format(last)}
            </text>
            <circle cx={px(n - 1)} cy={py(last)} r="5" fill={s.color} stroke="#fff" strokeWidth="2">
              <title>{`${s.name}: ${format(last)}`}</title>
            </circle>
            {s.values.map((v, i) => (
              <circle key={i} cx={px(i)} cy={py(v)} r="10" fill="transparent">
                <title>{`${labels[i]} · ${s.name}: ${format(v)}`}</title>
              </circle>
            ))}
          </g>
        );
      })}
      {labels.map((l, i) =>
        i % 2 === n % 2 || i === n - 1 ? (
          <text key={l} x={px(i)} y={h - 4} textAnchor={i === n - 1 ? "end" : i === 0 ? "start" : "middle"} fontSize="11" fill="#6A7683">
            {l}
          </text>
        ) : null,
      )}
    </svg>
  );
}

// ------------------------------------------------------------------ profit potential split

/** How the profit potential splits on a dark hero: losses vs missed profit, one stacked bar. */
export function ProfitSplit({ losses, missed, format }: { losses: number; missed: number; format: (n: number) => string }) {
  const total = losses + missed || 1;
  const rows = [
    { label: "Потери", note: "перерасход, переплаты, списания", value: losses, color: "bg-[#ff8a80]" },
    { label: "Упущенная выгода", note: "цены в меню, лучшие поставщики", value: missed, color: "bg-[#9be3a9]" },
  ];
  return (
    <div className="mt-5 max-w-md">
      <div className="flex h-2 overflow-hidden rounded-full bg-white/10" aria-hidden>
        {rows.map((r, i) => (
          <motion.div
            key={r.label}
            className={r.color}
            initial={{ width: 0 }}
            animate={{ width: `${(r.value / total) * 100}%` }}
            transition={{ duration: 0.6, ease: EASE, delay: 0.2 + i * 0.1 }}
          />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">
        {rows.map((r) => (
          <div key={r.label}>
            <dt className="flex items-center gap-1.5 text-white/70">
              <span className={cx("h-2 w-2 rounded-full", r.color)} aria-hidden />
              {r.label}
            </dt>
            <dd className="num mt-0.5 text-base font-semibold">{format(r.value)}</dd>
            <dd className="text-xs text-white/50">{r.note}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
