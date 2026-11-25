import { httpApi } from "./http";
import { mockApi } from "./mock";
import { ApiError, type Api } from "./types";

/**
 * VITE_USE_MOCKS:
 *   "true"   (default) everything on built-in demo data, no backend needed
 *   "hybrid" the real backend for everything it implements today (health, catalogue, sign-in);
 *            features that arrive in Phase 6 (wishlist, alerts, search history) say "coming soon"
 *   "false"  everything against the real API
 *
 * Demo data is never mixed with real data: demo wishlists reference demo products, which don't
 * exist in the real catalogue.
 */
export const API_MODE = (import.meta.env.VITE_USE_MOCKS ?? "true") as "true" | "hybrid" | "false";

/** True when the UI runs on built-in demo data (no backend). */
export const USE_MOCKS = API_MODE === "true";

const comingSoon = (): Promise<never> =>
  Promise.reject(
    new ApiError(503, {
      code: "coming_soon",
      message: "Wishlists, price alerts and search history are coming soon.",
    }),
  );

const hybridApi: Api = {
  ...httpApi,
  wishlist: { list: comingSoon, add: comingSoon, remove: comingSoon },
  alerts: { list: comingSoon, create: comingSoon, update: comingSoon, remove: comingSoon },
  history: { list: comingSoon, remove: comingSoon, clear: comingSoon },
};

export const api: Api = API_MODE === "false" ? httpApi : API_MODE === "hybrid" ? hybridApi : mockApi;

export * from "./types";
