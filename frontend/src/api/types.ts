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

export type BatchStatus = "failed" | "needs_matching" | "validated" | "published" | "rolled_back";

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
