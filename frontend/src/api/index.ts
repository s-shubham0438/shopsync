import { httpApi } from "./http";
import { mockApi } from "./mock";
import type { Api } from "./types";

export const USE_MOCKS = (import.meta.env.VITE_USE_MOCKS ?? "true") !== "false";

export const api: Api = USE_MOCKS ? mockApi : httpApi;

export * from "./types";
