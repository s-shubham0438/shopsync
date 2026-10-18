import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type ID, type PriceAlert, type SearchParams } from "@/api";

export const keys = {
  search: (p: SearchParams) => ["search", p] as const,
  deals: ["deals"] as const,
  product: (id: ID) => ["product", id] as const,
  history: (id: ID, days: number) => ["price-history", id, days] as const,
  categories: ["categories"] as const,
  platforms: ["platforms"] as const,
  me: ["me"] as const,
  wishlist: ["wishlist"] as const,
  alerts: ["alerts"] as const,
  searchHistory: ["search-history"] as const,
};

export const useSearch = (params: SearchParams, enabled = true) =>
  useQuery({
    queryKey: keys.search(params),
    queryFn: () => api.search(params),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useDeals = () => useQuery({ queryKey: keys.deals, queryFn: () => api.deals(8) });

export const useProduct = (id: ID) =>
  useQuery({ queryKey: keys.product(id), queryFn: () => api.getProduct(id) });

export const usePriceHistory = (id: ID, days: number) =>
  useQuery({
    queryKey: keys.history(id, days),
    queryFn: () => api.getPriceHistory(id, days),
    placeholderData: keepPreviousData,
  });

export const useCategories = () =>
  useQuery({ queryKey: keys.categories, queryFn: api.getCategories, staleTime: Infinity });

export const usePlatforms = () =>
  useQuery({ queryKey: keys.platforms, queryFn: api.getPlatforms, staleTime: Infinity });

// ---------------------------------------------------------------- protected ---

export const useWishlist = (enabled = true) =>
  useQuery({ queryKey: keys.wishlist, queryFn: api.wishlist.list, enabled });

export function useAddToWishlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, targetPrice }: { productId: ID; targetPrice?: number | null }) =>
      api.wishlist.add(productId, targetPrice),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.wishlist }),
  });
}

export function useRemoveFromWishlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: ID) => api.wishlist.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.wishlist }),
  });
}

export const useAlerts = (enabled = true) =>
  useQuery({ queryKey: keys.alerts, queryFn: api.alerts.list, enabled });

export function useCreateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, targetPrice }: { productId: ID; targetPrice: number }) =>
      api.alerts.create(productId, targetPrice),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}

export function useUpdateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: ID; patch: Partial<Pick<PriceAlert, "target_price" | "is_active">> }) =>
      api.alerts.update(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}

export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: ID) => api.alerts.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}

export const useSearchHistory = () =>
  useQuery({ queryKey: keys.searchHistory, queryFn: api.history.list });

export function useDeleteHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: ID | "all") => (id === "all" ? api.history.clear() : api.history.remove(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.searchHistory }),
  });
}
