export type Role = "hq_admin" | "hq_analyst" | "restaurant_director";

export const ROLE_LABELS: Record<Role, string> = {
  hq_admin: "Администратор УК",
  hq_analyst: "Аналитик УК",
  restaurant_director: "Директор ресторана",
};

export interface Me {
  id: string;
  email: string;
  full_name: string;
  tenant_id: string;
  role: Role;
  restaurant: { id: string; code: string; name: string } | null;
  permissions: string[];
}

export interface Restaurant {
  id: string;
  code: string;
  name: string;
  city: string | null;
  format: string | null;
  opened_on: string | null;
}

// ------------------------------------------------------------------ data import (backend/app/imports)

export type BatchStatus =
  | "failed"
  | "needs_matching"
  | "validated"
  | "published"
  | "rolled_back";

export interface ImportIssue {
  row: number | null;
  column: string | null;
  message: string;
}

export interface ImportBatch {
  id: string;
  restaurant_id: string | null;
  template: string;
  filename: string;
  status: BatchStatus;
  rows_total: number;
  rows_valid: number;
  period_from: string | null; // ISO date
  period_to: string | null;
  errors: ImportIssue[];
  warnings: ImportIssue[];
  column_map: Record<string, string>; // column title -> column number in the file
  unmatched: UnmatchedName[];
  created_at: string;
  published_at: string | null;
}

export type MatchKind = "product" | "menu_item" | "supplier";

/** A name from a file the catalog does not know yet, with suggestions to confirm once. */
export interface UnmatchedName {
  kind: MatchKind;
  code: string | null;
  name: string | null;
  key: string;
  rows: number[];
  rows_count: number;
  candidates: { id: string; name: string; score: number }[];
}

export interface CatalogOption {
  id: string;
  code: string;
  name: string;
}

export interface ImportTemplate {
  name: string;
  title: string;
  scope: "network" | "restaurant";
  columns: { title: string; required: boolean; synonyms: string[] }[];
  one_of: string[][];
}

export interface Freshness {
  restaurant_id: string;
  template: string;
  last_date: string | null;
  status: "good" | "stale" | "missing";
}

export interface NameAlias {
  id: string;
  kind: MatchKind;
  source_text: string;
  target_id: string;
  target_name: string;
  restaurant_id: string | null; // null: for the whole network
  created_at: string;
  files: number;
}

export interface AffectedFiles {
  affected_files: {
    id: string;
    filename: string;
    template: string;
    restaurant_id: string | null;
  }[];
}

export type ReasonKind = "loss" | "planned" | "shortage";

export interface WriteOffReason {
  code: string;
  title: string;
  kind: ReasonKind;
  synonyms: string[]; // how the reason is written in exports
}

/** Norms of the network: what counts as a problem. Percentages come as decimal strings. */
export interface Norms {
  food_cost_target_pct: string;
  food_cost_by_category: Record<string, string>;
  loss_default_pct: string;
  loss_by_category: Record<string, string>;
  write_off_reasons: WriteOffReason[];
  review_findings: boolean; // engine findings wait for HQ's check before directors see them
  menu_categories: string[];
  product_categories: string[];
}

export type ReviewStatus = "pending" | "confirmed" | "rejected";
export type RejectReason = "data" | "logic" | "false_alarm" | "other";

/** A finding as the API returns it (engine findings carry module, period and review state). */
export interface ApiFinding {
  id: string;
  restaurant_id: string | null; // null: network-wide
  kind: "problem" | "opportunity";
  process: string;
  module: string | null;
  confidence: "high" | "medium" | "low" | null;
  period_from: string | null;
  period_to: string | null;
  review_status: ReviewStatus | null;
  review_reason: RejectReason | null;
  review_note: string | null;
  reviewed_on: string | null;
  title: string;
  headline: string | null;
  effect_rub_month: string | null;
  effect_note: string | null;
  actions: string[];
  status: string;
  found_on: string;
}

export interface VerificationStep {
  id: string;
  label: string;
  value: string | null;
  unit: string;
  rows: Record<string, string | number | boolean | null>[];
}

/** A finding computed again from the uploaded rows: the steps, the rule that fired, the cross-checks. */
export interface Verification {
  module: string | null;
  supported: boolean;
  note?: string;
  formula?: string;
  object?: string;
  restaurant?: string;
  period?: [string | null, string | null];
  steps?: VerificationStep[];
  result?: { label: string; value: string | null; unit: string }[];
  rules?: { rule: string; value: string; threshold: string; passed: boolean }[];
  checks?: { check: string; ok: boolean; note?: string | null }[];
  history?: {
    from: string;
    to: string;
    share: string;
    theory: string;
    actual: string;
    write_off: string;
    unit_cost: string | null;
  }[];
  interpretation?: string[];
}

export interface AnalyticsRun {
  created: number;
  updated: number;
  removed: number;
  drafts: number;
}
