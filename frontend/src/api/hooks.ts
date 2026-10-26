import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
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
} from "./types";

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
