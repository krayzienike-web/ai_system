// Shapes of the data the prototype screens need. They are the contract for the analytics API
// (stages 3–7): the real endpoints should return the same structures.

export type ProcessKey =
  | "purchasing"
  | "receiving"
  | "storage"
  | "production"
  | "writeoffs"
  | "inventory"
  | "accounting"
  | "planning";

export type FindingKind = "problem" | "opportunity";
export type Confidence = "high" | "medium" | "low";
export type FindingStatus = "new" | "in_work" | "in_experiment" | "resolved";
export type Status = "good" | "warning" | "critical";

export interface RestaurantInfo {
  id: string;
  code: string;
  name: string;
  city: string;
  revenueMonth: number;
}

export interface ChartSpec {
  title: string;
  /** One-sentence conclusion shown above the chart. */
  conclusion?: string;
  unit: string;
  labels: string[];
  restaurant: number[];
  networkAvg?: number[];
  norm?: number;
  normLabel?: string;
}

export interface EvidenceTable {
  title: string;
  columns: string[];
  rows: (string | number)[][];
}

export interface Finding {
  id: string;
  kind: FindingKind;
  process: ProcessKey;
  restaurantId: string | null; // null = network-wide finding
  title: string;
  /** ₽ per month: losses for a problem, potential for an opportunity; null when not estimable. */
  effectRubMonth: number | null;
  effectNote?: string;
  confidence: Confidence;
  confidenceNote: string;
  metric: { label: string; value: string; benchmark: string; norm?: string };
  summary: string;
  causes: string[];
  actions: string[];
  chart?: ChartSpec;
  evidence?: EvidenceTable;
  status: FindingStatus;
  /** Plain-language conclusion: what is happening and why it matters. */
  headline?: string;
  /** "Me / network / norm" on one scale. */
  scale?: ScaleSpec;
  /** How the used quantity splits (by recipe norm / written off / unexplained). */
  composition?: CompositionSpec;
}

export interface ScaleSpec {
  label: string;
  unit: string;
  me: number;
  network?: number;
  networkLabel?: string;
  norm?: number;
  lowerIsBetter: boolean;
}

export interface CompositionSpec {
  unit: string;
  formula: string;
  parts: { label: string; value: number; tone: "brand" | "neutral" | "loss" | "gain" }[];
}

export interface WeeklyTrend {
  labels: string[];
  onTable: number[]; // ₽/month that can be returned, as estimated each week
  returned: number[]; // ₽/month confirmed by experiments, run-rate
}

export interface Kpis {
  foodCostActual: number; // %, last closed inventory period
  foodCostTheoretical: number; // %, last 4 weeks
  writeoffsPct: number; // % of revenue, last 4 weeks
  overpayRubMonth: number;
}

export interface StockRisk {
  restaurantId: string;
  product: string;
  daysLeft: number;
  nextDeliveryInDays: number;
  supplier: string;
}

export interface Task {
  id: string;
  restaurantId: string;
  title: string;
  source: string; // where the task came from
  findingId?: string;
  experimentId?: string;
  /** Who set the task: HQ assigns, a director takes it from the digest or adds it. */
  assignedBy: "hq" | "director";
  createdAt: string;
  due: string;
  status: "assigned" | "in_progress" | "done" | "overdue";
  checklist?: string[];
  report?: string;
  doneAt?: string;
  /** Measured outcome: computed by the analytics layer after the next recount or at the end of a check. */
  outcome?: TaskOutcome;
}

export interface TaskOutcome {
  verdict: "confirmed" | "not_confirmed" | "pending";
  /** Measured change in profit, ₽/month. */
  effectRubMonth?: number;
  /** How it was measured, in words. */
  text: string;
  measuredOn?: string;
}

export interface Experiment {
  id: string;
  title: string;
  hypothesis: string;
  findingId?: string;
  design: string;
  test: string[]; // restaurant ids
  control: string[];
  metric: string;
  baseline: string;
  period: string;
  expectedRubMonth: number;
  status: "proposed" | "running" | "completed";
  progress?: string;
  result?: {
    verdict: "confirmed" | "inconclusive" | "rejected";
    effectRubMonth: number;
    ciLow: number;
    ciHigh: number;
    text: string;
    rolloutRubMonth?: number;
  };
}

export interface DataSourceFreshness {
  restaurantId: string;
  source: "r_keeper" | "iiko" | "erp";
  dataset: string;
  lastDate: string;
  status: Status;
  note?: string;
}
