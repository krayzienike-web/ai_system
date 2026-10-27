// Generated from the API's OpenAPI schema by `python -m app.openapi` (backend). Do not edit.

export interface AliasChangeIn {
  target_id: string;
}

export interface AliasChangeOut {
  affected_files: FileRef[];
}

export type AliasKind = "product" | "menu_item" | "supplier";

export interface AliasOut {
  id: string;
  kind: string;
  source_text: string;
  target_id: string;
  target_name: string;
  restaurant_id: string | null;
  created_at: string;
  files: number;
}

export interface AnswerOut {
  text: string;
  columns: string[];
  rows: string[][];
  source_finding_id: string | null;
  source: string | null;
  suggestions: string[];
}

export interface AskIn {
  question: string;
  finding_id?: string | null;
}

export interface BadgesOut {
  inbox: number;
  open_tasks: number;
}

export interface BatchOut {
  id: string;
  restaurant_id: string | null;
  template: string;
  filename: string;
  status: string;
  rows_total: number;
  rows_valid: number;
  period_from: string | null;
  period_to: string | null;
  errors: Record<string, unknown>[];
  warnings: Record<string, unknown>[];
  column_map: Record<string, string>;
  unmatched: Record<string, unknown>[];
  aliases_used: string[];
  created_at: string;
  published_at: string | null;
}

export interface BoardOut {
  kinds: KindTotal[];
  stage_counts: Record<string, number>;
  late_count: number;
  processes: string[];
  groups: GroupOut[];
  max_effect: string;
}

export interface Body_upload_api_imports_post {
  file: string;
  template?: string | null;
  restaurant_id?: string | null;
}

export interface CandidateOut {
  restaurant_id: string;
  code: string;
  name: string;
  suggested: boolean;
  reason: string;
}

export interface CatalogOption {
  id: string;
  code: string;
  name: string;
}

export interface ChartView {
  title: string;
  conclusion?: string | null;
  unit: string;
  labels: string[];
  restaurant: (number | null)[];
  network_avg?: (number | null)[] | null;
  norm?: number | null;
  norm_label?: string | null;
}

export interface CheckDetailOut {
  id: string;
  finding_id: string | null;
  title: string;
  hypothesis: string;
  metric: string;
  test_restaurant_ids: string[];
  control_restaurant_ids: string[];
  starts_on: string;
  ends_on: string;
  expected_rub_month: string;
  status: "proposed" | "running" | "completed" | "rejected";
  verdict: "confirmed" | "inconclusive" | "rejected" | null;
  effect_rub_month: string | null;
  ci_low_rub_month: string | null;
  ci_high_rub_month: string | null;
  result_text: string | null;
  baseline: string | null;
  progress_text: string | null;
  rollout_rub_month: string | null;
  rollout_on: string | null;
  completed_on: string | null;
  finding_title?: string | null;
  test?: PlaceOut[];
  control?: PlaceOut[];
  tasks: TaskOut[];
  /** How many weeks the check runs. */
  weeks: number;
}

export interface CheckOut {
  id: string;
  finding_id: string | null;
  title: string;
  hypothesis: string;
  metric: string;
  test_restaurant_ids: string[];
  control_restaurant_ids: string[];
  starts_on: string;
  ends_on: string;
  expected_rub_month: string;
  status: "proposed" | "running" | "completed" | "rejected";
  verdict: "confirmed" | "inconclusive" | "rejected" | null;
  effect_rub_month: string | null;
  ci_low_rub_month: string | null;
  ci_high_rub_month: string | null;
  result_text: string | null;
  baseline: string | null;
  progress_text: string | null;
  rollout_rub_month: string | null;
  rollout_on: string | null;
  completed_on: string | null;
  finding_title?: string | null;
  test?: PlaceOut[];
  control?: PlaceOut[];
  /** How many weeks the check runs. */
  weeks: number;
}

export interface CheckRef {
  id: string;
  title: string;
  status: string;
  verdict: string | null;
  effect_rub_month: string | null;
  expected_rub_month: string;
  starts_on: string;
  ends_on: string;
  progress_text?: string | null;
}

export interface CommonOut {
  key: string;
  process: string;
  title: string;
  where: string;
  losses: string | null;
  note: string;
  finding_id: string | null;
}

export interface CompleteIn {
  report: string;
}

export interface CompositionPart {
  label: string;
  value: number | null;
  tone: string;
}

export interface CompositionView {
  unit: string;
  formula: string;
  parts: CompositionPart[];
  answer?: string | null;
}

export interface ContextOut {
  today: string;
  data_until: string | null;
  next_count_on: string | null;
  due_options: DueOption[];
  periods: PeriodOption[];
}

export interface DraftOut {
  finding_id: string;
  finding_title: string;
  actions: string[];
  test: PlaceOut;
  candidates: CandidateOut[];
  durations: DurationOut[];
  default_weeks: number;
  expected_rub_month: string;
  success: string;
}

export interface DueOption {
  label: string;
  days: number;
  due_on: string;
}

export interface DurationOut {
  weeks: number;
  note: string;
}

export interface EngineParamOut {
  key: string;
  module: string;
  title: string;
  unit: string;
  meaning: string;
  low: string;
  high: string;
  value: string;
  default: string;
}

export interface EngineParamsIn {
  values: Record<string, number | string | null>;
}

export type ExperimentStatus = "proposed" | "running" | "completed" | "rejected";

export interface FailureOut {
  kind: string;
  title: string;
  restaurant_ids: string[];
  reason: string;
  where?: string;
}

export interface FileRef {
  id: string;
  filename: string;
  template: string;
  restaurant_id: string | null;
}

export interface FindingDetailOut {
  id: string;
  restaurant_id: string | null;
  kind: "problem" | "opportunity";
  process: "purchasing" | "receiving" | "storage" | "production" | "writeoffs" | "inventory" | "accounting" | "planning";
  module: string | null;
  confidence: "high" | "medium" | "low" | null;
  period_from: string | null;
  period_to: string | null;
  review_status: ReviewStatus | null;
  review_reason: RejectReason | null;
  review_note: string | null;
  reviewed_on: string | null;
  reviewed_by_name?: string | null;
  title: string;
  headline: string | null;
  effect_rub_month: string | null;
  effect_note: string | null;
  actions: string[];
  status: "new" | "in_work" | "in_experiment" | "resolved" | "dismissed";
  found_on: string;
  work: WorkOut;
  restaurant_code?: string | null;
  restaurant_name?: string | null;
  view?: FindingView | null;
  tasks: TaskOut[];
  check: CheckRef | null;
  result_answer: string | null;
  /** «около … в год»: the monthly effect × 12. */
  effect_rub_year: string | null;
}

export interface FindingOut {
  id: string;
  restaurant_id: string | null;
  kind: "problem" | "opportunity";
  process: "purchasing" | "receiving" | "storage" | "production" | "writeoffs" | "inventory" | "accounting" | "planning";
  module: string | null;
  confidence: "high" | "medium" | "low" | null;
  period_from: string | null;
  period_to: string | null;
  review_status: ReviewStatus | null;
  review_reason: RejectReason | null;
  review_note: string | null;
  reviewed_on: string | null;
  reviewed_by_name?: string | null;
  title: string;
  headline: string | null;
  effect_rub_month: string | null;
  effect_note: string | null;
  actions: string[];
  status: "new" | "in_work" | "in_experiment" | "resolved" | "dismissed";
  found_on: string;
  work: WorkOut;
  restaurant_code?: string | null;
  restaurant_name?: string | null;
  view?: FindingView | null;
  /** «около … в год»: the monthly effect × 12. */
  effect_rub_year: string | null;
}

/** How a finding is shown (analytics/views.py; hand-made findings carry the same blocks). */
export interface FindingView {
  summary?: string | null;
  causes?: string[];
  confidence_note?: string | null;
  metric?: MetricView | null;
  scale?: ScaleView | null;
  composition?: CompositionView | null;
  chart?: ChartView | null;
  table?: TableView | null;
}

export interface FreshnessOut {
  restaurant_id: string;
  template: string;
  last_date: string | null;
  status: string;
}

export interface GroupOut {
  key: string;
  title: string;
  count: number;
  total: string;
  items: FindingOut[];
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface HeadReportOut {
  date_from: string;
  date_to: string;
  found_rub_month: string;
  in_work_rub_month: string;
  confirmed_rub_month: string;
  open_findings_before: number;
  open_findings_now: number;
  closed_findings: number;
  potential_before_rub_month: string;
  potential_now_rub_month: string;
  tasks_set: number;
  tasks_done: number;
  done_tasks: TaskOut[];
  failures: FailureOut[];
  network_name: string;
  confirmed_by_tasks_rub_month: string;
  trend: TrendOut;
  trend_answer: string;
  found_rub_year: string;
  in_work_rub_year: string;
  confirmed_rub_year: string;
  checks: CheckOut[];
}

export interface KindTotal {
  kind: string;
  count: number;
  total: string;
}

export interface KpiOut {
  food_cost_actual: string | null;
  food_cost_theory: string | null;
  write_offs_share: string | null;
  food_cost_from: string | null;
  food_cost_to: string | null;
}

/** When the findings were last recomputed, and whether a run is waiting or going on now. */
export interface LatestRunOut {
  status: "queued" | "running" | "done" | "failed";
  trigger: "upload" | "manual";
  requested_at: string;
  finished_at: string | null;
  created: number | null;
  updated: number | null;
  removed: number | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface MatchIn {
  kind: AliasKind;
  key: string;
  target_id: string;
}

export interface MatchesIn {
  matches: MatchIn[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  tenant_id: string;
  role: Role;
  restaurant: app__auth__api__RestaurantRef | null;
  permissions: Permission[];
}

export interface MetricView {
  label: string;
  value: string;
  benchmark: string;
  norm?: string | null;
}

export interface NetworkOut {
  restaurants: number;
  losses: string;
  potential: string;
  on_table: string;
  on_table_year: string;
  found_count: number;
  confirmed: string;
  completed_checks: number;
  checks_waiting: number;
  overdue_tasks: number;
  trend: TrendOut;
  ranking: RankOut[];
  common: CommonOut[];
}

export interface NormsIn {
  food_cost_target_pct: number | string;
  food_cost_by_category?: Record<string, number | string>;
  loss_default_pct: number | string;
  loss_by_category?: Record<string, number | string>;
  write_off_reasons?: ReasonIO[];
  review_findings?: boolean;
}

export interface NormsOut {
  food_cost_target_pct: string;
  food_cost_by_category?: Record<string, string>;
  loss_default_pct: string;
  loss_by_category?: Record<string, string>;
  write_off_reasons?: ReasonIO[];
  review_findings?: boolean;
  menu_categories: string[];
  product_categories: string[];
}

export interface OutcomeOut {
  verdict: "pending" | "confirmed" | "not_confirmed";
  effect_rub_month: string | null;
  text: string | null;
  measured_on: string | null;
}

export interface PeriodOption {
  preset: PeriodPreset;
  title: string;
  date_from: string;
  date_to: string;
}

export type PeriodPreset = "week" | "prev_week" | "4w" | "13w" | "month" | "quarter" | "since_count";

export type Permission = "restaurants.read" | "restaurants.manage" | "users.manage" | "network.compare" | "data.upload" | "catalog.manage" | "experiments.propose" | "experiments.launch" | "analytics.run" | "findings.review" | "norms.manage" | "tasks.assign" | "tasks.execute" | "ai.chat";

export interface PlaceOut {
  id: string;
  code: string;
  name: string;
}

export interface ProcessOut {
  process: string;
  title: string;
  losses: string;
  findings: FindingOut[];
}

export interface ProposeIn {
  finding_id: string;
  action: string;
  control_ids?: string[];
  weeks: number;
}

export interface RankOut {
  restaurant_id: string;
  code: string;
  name: string;
  losses: string;
  delta: string | null;
  top_problem: string | null;
}

export interface ReasonIO {
  code: string;
  title: string;
  kind: "loss" | "planned" | "shortage";
  synonyms?: string[];
}

export interface RefreshRequest {
  refresh_token: string;
}

export type RejectReason = "data" | "logic" | "false_alarm" | "other";

export interface RestaurantIn {
  code: string;
  name: string;
  city?: string | null;
  format?: string | null;
  opened_on?: string | null;
}

export interface RestaurantOut {
  id: string;
  code: string;
  name: string;
  city: string | null;
  format: string | null;
  opened_on: string | null;
}

export interface RestaurantRowOut {
  id: string;
  code: string;
  name: string;
  city: string | null;
  losses: string;
  potential: string;
  delta: string | null;
  food_cost: string | null;
  late: number;
  tasks_done: number;
  tasks_total: number;
  bad_processes: number;
  stale_data: string | null;
}

export interface ReviewIn {
  verdict: Verdict;
  reason?: RejectReason | null;
  note?: string | null;
}

export type ReviewStatus = "pending" | "confirmed" | "rejected";

export type Role = "hq_admin" | "hq_analyst" | "restaurant_director";

export interface RunOut {
  created: number;
  updated: number;
  removed: number;
  drafts: number;
}

/** «Me / network / norm» on one scale; `answer` — «Это много?» in words. */
export interface ScaleView {
  label: string;
  unit: string;
  me: number | null;
  network?: number | null;
  network_label?: string | null;
  norm?: number | null;
  norm_label?: string | null;
  lower_is_better: boolean;
  answer?: string | null;
}

export interface TableView {
  title: string;
  columns: string[];
  rows: ((string | number | null)[])[];
}

export interface TaskIn {
  title: string;
  due_on: string;
  finding_id?: string | null;
  restaurant_ids?: string[] | null;
  checklist?: string[];
}

export interface TaskOut {
  id: string;
  restaurant_id: string;
  finding_id: string | null;
  experiment_id: string | null;
  title: string;
  checklist: string[];
  checklist_done: boolean[];
  assigned_by: "hq" | "director";
  created_on: string;
  due_on: string;
  status: "assigned" | "in_progress" | "done";
  late: boolean;
  days_left: number;
  done_on: string | null;
  report: string | null;
  outcome: OutcomeOut | null;
  reminded_on: string | null;
  source?: string | null;
  finding_title?: string | null;
  finding_effect_rub_month?: string | null;
  restaurant_code?: string | null;
  restaurant_name?: string | null;
}

export interface TemplateColumnOut {
  title: string;
  required: boolean;
  synonyms: string[];
}

export interface TemplateOut {
  name: string;
  title: string;
  scope: string;
  columns: TemplateColumnOut[];
  one_of: string[][];
}

export interface TickIn {
  index: number;
  done: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

export interface TrendOut {
  labels: string[];
  week_ends: string[];
  on_table: string[];
  returned: string[];
  open_findings: number[];
  change: string | null;
  change_pct: number | null;
  span: string;
  answer: string;
}

export interface UserIn {
  email: string;
  full_name: string;
  password: string;
  role: Role;
  restaurant_id?: string | null;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  role: Role;
  restaurant_id: string | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export type Verdict = "confirm" | "reject" | "reopen";

export interface WeekOut {
  restaurant: app__overview__api__RestaurantRef;
  losses: string;
  potential: string;
  on_table: string;
  found_count: number;
  delta_week: string | null;
  digest: string;
  digest_findings: FindingOut[];
  actions: FindingOut[];
  top: FindingOut[];
  processes: ProcessOut[];
  fine_processes: string[];
  kpi: KpiOut | null;
  network_kpi: KpiOut | null;
  kpi_answer: string | null;
  stock_risks: Record<string, string>[];
  done_tasks: TaskOut[];
  results_answer: string;
}

export interface WorkOut {
  stage: WorkStage;
  tasks_total: number;
  tasks_done: number;
  tasks_late: number;
  confirmed_rub_month: string;
  check_waiting_launch: boolean;
}

export type WorkStage = "new" | "doing" | "checking" | "done";

export interface app__auth__api__RestaurantRef {
  id: string;
  code: string;
  name: string;
}

export interface app__overview__api__RestaurantRef {
  id: string;
  code: string;
  name: string;
  city: string | null;
}
