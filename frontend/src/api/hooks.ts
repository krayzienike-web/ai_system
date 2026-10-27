import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "./client";
import type {
  LatestRun,
  AffectedFiles,
  CatalogOption,
  Freshness,
  ImportBatch,
  ImportTemplate,
  MatchKind,
  Me,
  NameAlias,
  Restaurant,
  Norms,
  AnalyticsRun,
  ApiFinding,
  RejectReason,
  ReviewStatus,
  Verification,
  EngineParam,
  ApiTask,
  AppContext,
  Badges,
  ChatAnswer,
  Check,
  CheckDetail,
  CheckDraft,
  FindingDetail,
  FindingBoard,
  HeadReport,
  NetworkOverview,
  RestaurantRow,
  RestaurantWeek,
} from "./types";
import type { PeriodChoice } from "../state/ui";

export const useMe = () =>
  useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

export const useRestaurants = () =>
  useQuery({
    queryKey: ["restaurants"],
    queryFn: () => api<Restaurant[]>("/restaurants"),
  });

// ------------------------------------------------------------------ data import

export const useImportTemplates = () =>
  useQuery({
    queryKey: ["imports", "templates"],
    queryFn: () => api<ImportTemplate[]>("/imports/templates"),
    staleTime: Infinity,
  });

export const useImports = () =>
  useQuery({
    queryKey: ["imports", "list"],
    queryFn: () => api<ImportBatch[]>("/imports"),
  });

export const useFreshness = () =>
  useQuery({
    queryKey: ["imports", "freshness"],
    queryFn: () => api<Freshness[]>("/imports/freshness"),
  });

export function useUploadImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      restaurantId,
      template,
    }: {
      file: File;
      restaurantId: string | null;
      template: string | null;
    }) => {
      const form = new FormData();
      form.append("file", file);
      if (restaurantId) form.append("restaurant_id", restaurantId);
      if (template) form.append("template", template);
      return api<ImportBatch>("/imports", { method: "POST", body: form });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["imports"] }),
  });
}

export function useBatchAction(action: "publish" | "rollback" | "reprocess") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api<ImportBatch>(`/imports/${id}/${action}`, { method: "POST" }),
    // Publishing changes how many files rely on each remembered match.
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["imports"] });
      void client.invalidateQueries({ queryKey: ["aliases"] });
      void client.invalidateQueries({ queryKey: ["analytics-run"] }); // the findings are being recomputed
    },
  });
}

export const useCatalog = (kind: MatchKind) =>
  useQuery({
    queryKey: ["catalog", kind],
    queryFn: () => api<CatalogOption[]>(`/catalog/${kind}`),
  });

export function useMatchNames() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      matches,
    }: {
      id: string;
      matches: { kind: MatchKind; key: string; target_id: string }[];
    }) =>
      api<ImportBatch>(`/imports/${id}/match`, {
        method: "POST",
        body: JSON.stringify({ matches }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["imports"] });
      void client.invalidateQueries({ queryKey: ["aliases"] });
      void client.invalidateQueries({ queryKey: ["analytics-run"] }); // the findings are being recomputed
    },
  });
}

export const useAliases = () =>
  useQuery({
    queryKey: ["aliases"],
    queryFn: () => api<NameAlias[]>("/aliases"),
  });

export function useAliasEdit() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, targetId }: { id: string; targetId: string | null }) =>
      targetId
        ? api<AffectedFiles>(`/aliases/${id}`, {
            method: "PUT",
            body: JSON.stringify({ target_id: targetId }),
          })
        : api<AffectedFiles>(`/aliases/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["aliases"] }),
  });
}

export const useNorms = () =>
  useQuery({
    queryKey: ["norms"],
    queryFn: () => api<Norms>("/settings/norms"),
  });

export function useSaveNorms() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (
      norms: Omit<Norms, "menu_categories" | "product_categories">,
    ) =>
      api<Norms>("/settings/norms", {
        method: "PUT",
        body: JSON.stringify(norms),
      }),
    onSuccess: (saved) => client.setQueryData(["norms"], saved),
  });
}

// ------------------------------------------------------------------ review of engine findings

export const useReviewFindings = (status: ReviewStatus, enabled = true) =>
  useQuery({
    queryKey: ["review", status],
    queryFn: () => api<ApiFinding[]>(`/findings?review=${status}`),
    enabled,
  });

export const useVerification = (id: string) =>
  useQuery({
    queryKey: ["verification", id],
    queryFn: () => api<Verification>(`/findings/${id}/verification`),
  });

export function useReviewFinding() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string;
      verdict: "confirm" | "reject" | "reopen";
      reason?: RejectReason;
      note?: string;
    }) =>
      api<ApiFinding>(`/findings/${id}/review`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => refreshWork(client),
  });
}

const RUN_POLL_MS = 3000;
/** The server marks a run that went on longer as interrupted; a run waiting longer than this has no worker. */
const RUN_POLL_LIMIT_MS = 30 * 60_000;

/** The latest recalculation; polled while one waits or runs, never on error and not forever. */
export function useLatestRun() {
  return useQuery({
    queryKey: ["analytics-run"],
    queryFn: () => api<LatestRun | null>("/analytics/runs/latest"),
    refetchInterval: (q) => runPollInterval(q.state.data, q.state.error, Date.now()),
  });
}

export function runPollInterval(run: LatestRun | null | undefined, error: unknown, now: number): number | false {
  if (error || !run || !["queued", "running"].includes(run.status)) return false;
  return now - Date.parse(run.requested_at) < RUN_POLL_LIMIT_MS ? RUN_POLL_MS : false;
}

/** Mounted once in the shell: when a recalculation finishes, whatever screen is open shows the new findings. */
export function useRefreshWhenRunIsDone() {
  const client = useQueryClient();
  const status = useLatestRun().data?.status;
  const before = useRef(status);
  useEffect(() => {
    if (before.current && ["queued", "running"].includes(before.current) && status === "done") refreshWork(client);
    before.current = status;
  }, [status, client]);
}

export function useRunAnalytics() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<AnalyticsRun>("/analytics/run", { method: "POST" }),
    onSuccess: () => {
      refreshWork(client);
      void client.invalidateQueries({ queryKey: ["analytics-run"] });
    },
  });
}

// ------------------------------------------------------------------ engine parameters

export const useEngineParams = () =>
  useQuery({
    queryKey: ["engine-params"],
    queryFn: () => api<EngineParam[]>("/settings/engine"),
  });

export function useSaveEngineParams() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string | null>) =>
      api<EngineParam[]>("/settings/engine", {
        method: "PUT",
        body: JSON.stringify({ values }),
      }),
    onSuccess: (saved) => client.setQueryData(["engine-params"], saved),
  });
}

// ------------------------------------------------------------------ screens (ADR 0007: the API computes, screens draw)

/** After an action, everything that is computed from the work on findings is stale. */
const STATIC = new Set(["me", "restaurants", "imports/templates", "catalog", "norms", "engine-params", "context"]);
export const isStatic = (key: readonly unknown[]) => STATIC.has(String(key[0])) || STATIC.has(`${String(key[0])}/${String(key[1])}`);
function refreshWork(client: ReturnType<typeof useQueryClient>) {
  return client.invalidateQueries({ predicate: (q) => !isStatic(q.queryKey) });
}

/** `?preset=week` or `?date_from=…&date_to=…` for the period chosen in the header. */
export function periodQuery(period: PeriodChoice): string {
  return "preset" in period
    ? `preset=${period.preset}`
    : `date_from=${period.from}&date_to=${period.to}`;
}

export const useAppContext = () =>
  useQuery({ queryKey: ["context"], queryFn: () => api<AppContext>("/overview/context"), staleTime: 60_000 });

export const useBadges = () =>
  useQuery({ queryKey: ["badges"], queryFn: () => api<Badges>("/overview/badges") });

export const useNetworkOverview = (period: PeriodChoice) =>
  useQuery({
    queryKey: ["overview", "network", period],
    queryFn: () => api<NetworkOverview>(`/overview/network?${periodQuery(period)}`),
  });

export const useRestaurantWeek = (code: string) =>
  useQuery({
    queryKey: ["overview", "restaurant", code],
    queryFn: () => api<RestaurantWeek>(`/overview/restaurants/${code}`),
  });

export const useRestaurantRows = () =>
  useQuery({ queryKey: ["overview", "restaurants"], queryFn: () => api<RestaurantRow[]>("/overview/restaurants") });

export interface BoardFilters {
  kind?: "problem" | "opportunity";
  process?: string;
  restaurant?: string; // restaurant id or "net"
  stage?: string;
  late?: boolean;
}

export const useFindingBoard = (filters: BoardFilters) =>
  useQuery({
    queryKey: ["board", filters],
    queryFn: () => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) if (v !== undefined && v !== false) q.set(k, String(v));
      return api<FindingBoard>(`/overview/findings?${q}`);
    },
    placeholderData: (previous) => previous,
  });

export const useFindings = () =>
  useQuery({ queryKey: ["findings"], queryFn: () => api<ApiFinding[]>("/findings") });

export const useFinding = (id: string) =>
  useQuery({ queryKey: ["finding", id], queryFn: () => api<FindingDetail>(`/findings/${id}`) });

export const useTasks = (late = false) =>
  useQuery({
    queryKey: ["tasks", late],
    queryFn: () => api<ApiTask[]>(late ? "/tasks?late=true" : "/tasks"),
  });

export interface NewTask {
  title: string;
  due_on: string;
  finding_id?: string;
  restaurant_ids?: string[];
  checklist?: string[];
}

export function useCreateTasks() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (task: NewTask) => api<ApiTask[]>("/tasks", { method: "POST", body: JSON.stringify(task) }),
    onSuccess: () => refreshWork(client),
  });
}

export function useTaskAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: "start" | "complete" | "checklist" | "remind"; body?: unknown }) =>
      api<ApiTask>(`/tasks/${id}/${action}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => refreshWork(client),
  });
}

export const useChecks = (status?: Check["status"]) =>
  useQuery({
    queryKey: ["checks", status ?? "all"],
    queryFn: () => api<Check[]>(status ? `/checks?status=${status}` : "/checks"),
  });

export const useCheck = (id: string) =>
  useQuery({ queryKey: ["check", id], queryFn: () => api<CheckDetail>(`/checks/${id}`) });

export const useCheckDraft = (findingId: string) =>
  useQuery({
    queryKey: ["check-draft", findingId],
    queryFn: () => api<CheckDraft>(`/checks/draft?finding_id=${findingId}`),
  });

export function useCheckAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "launch" | "reject" | "rollout" }) =>
      api<unknown>(`/checks/${id}/${action}`, { method: "POST" }),
    onSuccess: () => refreshWork(client),
  });
}

export function useProposeCheck() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { finding_id: string; action: string; control_ids: string[]; weeks: number }) =>
      api<Check>("/checks", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => refreshWork(client),
  });
}

export const useHeadReport = (period: PeriodChoice) =>
  useQuery({
    queryKey: ["report", period],
    queryFn: () => api<HeadReport>(`/reports/head?${periodQuery(period)}`),
  });

export const useChatSuggestions = () =>
  useQuery({ queryKey: ["chat-suggestions"], queryFn: () => api<string[]>("/chat/suggestions") });

export const useAsk = () =>
  useMutation({
    mutationFn: (body: { question: string; finding_id?: string }) =>
      api<ChatAnswer>("/chat", { method: "POST", body: JSON.stringify(body) }),
  });
