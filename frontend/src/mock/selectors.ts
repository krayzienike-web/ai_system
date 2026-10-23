import { EXPERIMENTS, FINDINGS, KPIS, RESTAURANTS } from "./data";
import type { Finding, Kpis, ProcessKey, Status } from "./types";

export const PROCESSES: { key: ProcessKey; title: string }[] = [
  { key: "purchasing", title: "Закупка" },
  { key: "receiving", title: "Приемка" },
  { key: "storage", title: "Хранение" },
  { key: "production", title: "Производство (ТТК)" },
  { key: "writeoffs", title: "Списания" },
  { key: "inventory", title: "Инвентаризация" },
  { key: "accounting", title: "Учет и данные" },
  { key: "planning", title: "Планирование запасов" },
];

export const processTitle = (key: ProcessKey) => PROCESSES.find((p) => p.key === key)?.title ?? key;

const byEffect = (a: Finding, b: Finding) => (b.effectRubMonth ?? -1) - (a.effectRubMonth ?? -1);
const sum = (items: Finding[]) => items.reduce((acc, f) => acc + (f.effectRubMonth ?? 0), 0);

export const findingById = (id: string) => FINDINGS.find((f) => f.id === id);

export const restaurantByCode = (code: string) => RESTAURANTS.find((r) => r.code === code);

/** Open findings of one restaurant (resolved ones are history, not "on the table"). */
export function restaurantFindings(restaurantId: string) {
  const open = FINDINGS.filter((f) => f.restaurantId === restaurantId && f.status !== "resolved");
  const problems = open.filter((f) => f.kind === "problem").sort(byEffect);
  const opportunities = open.filter((f) => f.kind === "opportunity").sort(byEffect);
  return { problems, opportunities, losses: sum(problems), potential: sum(opportunities) };
}

export function networkTotals() {
  const open = FINDINGS.filter((f) => f.status !== "resolved");
  const confirmed = EXPERIMENTS.filter((e) => e.result?.verdict === "confirmed").reduce(
    (acc, e) => acc + (e.result?.effectRubMonth ?? 0),
    0,
  );
  return {
    losses: sum(open.filter((f) => f.kind === "problem")),
    potential: sum(open.filter((f) => f.kind === "opportunity")),
    confirmed,
  };
}

/** Process status from open problems: ≥ 25k ₽/month or unmeasured data gaps escalate. */
export function processStatus(restaurantId: string, process: ProcessKey): { status: Status; losses: number } {
  const problems = FINDINGS.filter(
    (f) => f.restaurantId === restaurantId && f.process === process && f.kind === "problem" && f.status !== "resolved",
  );
  const losses = sum(problems);
  if (problems.length === 0) return { status: "good", losses };
  return { status: losses >= 25_000 ? "critical" : "warning", losses };
}

/** Revenue-weighted network averages — the only cross-restaurant view a director gets. */
export function networkKpis(): Kpis {
  const total = RESTAURANTS.reduce((acc, r) => acc + r.revenueMonth, 0);
  const avg = (pick: (k: Kpis) => number) =>
    RESTAURANTS.reduce((acc, r) => acc + pick(KPIS[r.code]!) * r.revenueMonth, 0) / total;
  return {
    foodCostActual: avg((k) => k.foodCostActual),
    foodCostTheoretical: avg((k) => k.foodCostTheoretical),
    writeoffsPct: avg((k) => k.writeoffsPct),
    overpayRubMonth: RESTAURANTS.reduce((acc, r) => acc + KPIS[r.code]!.overpayRubMonth, 0) / RESTAURANTS.length,
  };
}
