// Prototype "today" matches the demo data period; dates in the demo are "ДД.ММ" in 2026.
export const TODAY = new Date(2026, 9, 23);

const ddmm = (d: Date) => `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;

export const todayLabel = () => ddmm(TODAY);

/** "ДД.ММ" that is `days` from today. */
export function dateIn(days: number) {
  const d = new Date(TODAY);
  d.setDate(d.getDate() + days);
  return ddmm(d);
}

export function daysUntil(due: string) {
  const [d, m] = due.split(".").map(Number);
  const date = new Date(2026, (m ?? 1) - 1, d ?? 1);
  return Math.round((date.getTime() - TODAY.getTime()) / 86_400_000);
}

/** Due-date presets for task creation. */
export const DUE_PRESETS = [
  { label: "3 дня", days: 3 },
  { label: "Неделя", days: 7 },
  { label: "2 недели", days: 14 },
] as const;
