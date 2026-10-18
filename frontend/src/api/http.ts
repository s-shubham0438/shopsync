import {
  ApiError,
  type Api,
  type ApiErrorBody,
  type Category,
  type Page,
  type PriceAlert,
  type PriceHistory,
  type ProductDetail,
  type ProductSummary,
  type SearchHistoryItem,
  type SearchParams,
  type User,
  type WishlistItem,
} from "./types";

const BASE = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

type Query = Record<string, string | number | undefined | null>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (body?.error?.code) return new ApiError(res.status, body.error);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, { code: "http_error", message: res.statusText || "Request failed" });
}

let refreshing: Promise<boolean> | null = null;

/** Single-flight refresh: concurrent 401s share one /auth/refresh call. */
function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function request<T>(
  method: string,
  path: string,
  { query, body, retry = true }: { query?: Query; body?: unknown; retry?: boolean } = {},
): Promise<T> {
  const res = await fetch(BASE + withQuery(path, query), {
    method,
    credentials: "include", // httpOnly auth cookies
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await refreshSession()) return request<T>(method, path, { query, body, retry: false });
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(path: string, query?: Query) => request<T>("GET", path, { query });
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, { body });

export const httpApi: Api = {
  search: (p: SearchParams) => get<Page<ProductSummary>>("/search", { ...p }),
  deals: (limit = 8) => get<ProductSummary[]>("/deals", { limit }),
  getProduct: (id) => get<ProductDetail>(`/products/${id}`),
  getPriceHistory: (id, days) => get<PriceHistory>(`/products/${id}/price-history`, { days }),
  getCategories: () => get<Category[]>("/categories"),
  getPlatforms: () => get("/platforms"),
  buyUrl: (listing) => `${BASE}/go/${listing.id}`,

  auth: {
    async me() {
      try {
        return await get<User>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          if (await refreshSession()) return get<User>("/auth/me").catch(() => null);
          return null;
        }
        throw e;
      }
    },
    login: (email, password) => post<User>("/auth/login", { email, password }),
    signup: (full_name, email, password) => post<User>("/auth/signup", { full_name, email, password }),
    logout: () => post<void>("/auth/logout"),
    sendOtp: (phone) => post<void>("/auth/otp/send", { phone }),
    verifyOtp: (phone, code) => post<User>("/auth/otp/verify", { phone, code }),
    googleLoginUrl: () => `${BASE}/auth/google/login`,
  },

  wishlist: {
    list: () => get<Page<WishlistItem>>("/wishlist", { page_size: 100 }).then((p) => p.items),
    add: (product_id, target_price = null) => post<WishlistItem>("/wishlist", { product_id, target_price }),
    remove: (id) => request<void>("DELETE", `/wishlist/${id}`),
  },

  alerts: {
    list: () => get<Page<PriceAlert>>("/alerts", { page_size: 100 }).then((p) => p.items),
    create: (product_id, target_price) => post<PriceAlert>("/alerts", { product_id, target_price }),
    update: (id, patch) => request<PriceAlert>("PATCH", `/alerts/${id}`, { body: patch }),
    remove: (id) => request<void>("DELETE", `/alerts/${id}`),
  },

  history: {
    list: () =>
      get<Page<SearchHistoryItem>>("/search-history", { page_size: 50 }).then((p) => p.items),
    remove: (id) => request<void>("DELETE", `/search-history/${id}`),
    clear: () => request<void>("DELETE", "/search-history"),
  },
};
