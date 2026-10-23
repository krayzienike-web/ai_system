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
export type FindingStatus = "new" | "in_work" | "disputed" | "in_experiment" | "resolved";
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

export interface Improvement {
  restaurantId: string;
  text: string;
}

export interface Task {
  id: string;
  restaurantId: string;
  title: string;
  source: string; // where the task came from
  findingId?: string;
  experimentId?: string;
  due: string;
  status: "assigned" | "in_progress" | "done" | "overdue";
  checklist?: string[];
  report?: string;
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
