// Reporting period, the same rules as the API (backend/app/core/period.py): weeks Monday–Sunday,
// presets end on the last full week, "month" is the last full calendar month, a custom range is inclusive.
import { TODAY } from "./dates";

export type PeriodPreset = "week" | "prev_week" | "4w" | "13w" | "month";

export type PeriodChoice =
  | { preset: PeriodPreset }
  | { from: string; to: string }; // ISO dates

export interface Period {
  from: Date;
  to: Date;
  label: string;
  /** How many weekly points of a trend fall into the period (at least 2, so a line is still a line). */
  weeks: number;
}

export const PRESETS: { preset: PeriodPreset; title: string }[] = [
  { preset: "week", title: "Прошлая неделя" },
  { preset: "prev_week", title: "Неделя до нее" },
  { preset: "4w", title: "4 недели" },
  { preset: "13w", title: "13 недель" },
  { preset: "month", title: "Прошлый месяц" },
];

const DAY = 86_400_000;
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * DAY);
const short = (d: Date) =>
  d
    .toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    .replace(".", "");
export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Sunday of the last week that is over. */
export function lastFullWeekEnd(today = TODAY) {
  const isoWeekday = today.getDay() === 0 ? 7 : today.getDay();
  return addDays(today, -isoWeekday);
}

export function resolvePeriod(choice: PeriodChoice, today = TODAY): Period {
  let from: Date;
  let to: Date;
  let title: string;
  if ("preset" in choice && choice.preset === "month") {
    to = addDays(new Date(today.getFullYear(), today.getMonth(), 1), -1);
    from = new Date(to.getFullYear(), to.getMonth(), 1);
    title = "Прошлый месяц";
  } else if ("preset" in choice) {
    const weeks = { week: 1, prev_week: 1, "4w": 4, "13w": 13 }[
      choice.preset as Exclude<PeriodPreset, "month">
    ];
    to = addDays(
      lastFullWeekEnd(today),
      choice.preset === "prev_week" ? -7 : 0,
    );
    from = addDays(to, -(7 * weeks - 1));
    title = PRESETS.find((p) => p.preset === choice.preset)!.title;
  } else {
    from = new Date(`${choice.from}T00:00:00`);
    to = new Date(`${choice.to}T00:00:00`);
    title = "Период";
  }
  const days = Math.round((to.getTime() - from.getTime()) / DAY) + 1;
  return {
    from,
    to,
    label: `${title} · ${short(from)} – ${short(to)}`,
    weeks: Math.max(2, Math.ceil(days / 7) + 1),
  };
}

/** Error text for a custom range, or null when it is valid. */
export function customRangeError(
  from: string,
  to: string,
  today = TODAY,
): string | null {
  if (!from || !to) return "Укажите обе даты";
  if (from > to) return "Начало позже конца";
  if (to > iso(today)) return "Период не может заканчиваться в будущем";
  if ((new Date(to).getTime() - new Date(from).getTime()) / DAY + 1 > 366)
    return "Не больше года";
  return null;
}
