/**
 * In-memory implementation of the Api contract. Behaves like the real backend
 * (latency, 401s, validation errors) so screens can be built before the API exists.
 * Per-user data (session, wishlist, alerts, history) persists in localStorage.
 */
import {
  ApiError,
  type Api,
  type ID,
  type Page,
  type PriceAlert,
  type PriceHistory,
  type PricePoint,
  type ProductDetail,
  type ProductSummary,
  type SearchHistoryItem,
  type SearchParams,
  type User,
  type WishlistItem,
} from "../types";
import { CATEGORIES, CATEGORY_KEYWORDS, PLATFORMS, PRODUCTS, toSummary } from "./data";

export const MOCK_OTP = "123456";
const PAGE_SIZE = 12;
const DAY = 86_400_000;

const delay = (ms = 250 + Math.random() * 250) => new Promise((r) => setTimeout(r, ms));

// --------------------------------------------------------------------------- //
// Persistence (localStorage with in-memory fallback)
// --------------------------------------------------------------------------- //
interface Store {
  user: User | null;
  wishlist: { id: ID; product_id: ID; target_price: number | null; created_at: string }[];
  alerts: { id: ID; product_id: ID; target_price: number; is_active: boolean; last_notified_at: string | null; created_at: string }[];
  history: SearchHistoryItem[];
}

const KEY = "shopsync.mock.v1";
let memory: Store = { user: null, wishlist: [], alerts: [], history: [] };

function load(): Store {
  try {
    const raw = globalThis.localStorage?.getItem(KEY);
    if (raw) memory = JSON.parse(raw) as Store;
  } catch {
    /* storage unavailable */
  }
  return memory;
}

function save(store: Store): void {
  memory = store;
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify(store));
  } catch {
    /* storage unavailable */
  }
}

const uid = () => globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
const now = () => new Date().toISOString();

function requireUser(): User {
  const user = load().user;
  if (!user) throw new ApiError(401, { code: "unauthorized", message: "Authentication required." });
  return user;
}

function findProduct(id: ID): ProductDetail {
  const product = PRODUCTS.find((p) => p.id === id);
  if (!product) throw new ApiError(404, { code: "not_found", message: "Product not found." });
  return product;
}

// --------------------------------------------------------------------------- //
// Search
// --------------------------------------------------------------------------- //
function searchableText(p: ProductDetail): string {
  const cat = p.category;
  const parent = CATEGORIES.find((c) => c.id === cat?.parent_id);
  return [
    p.canonical_title,
    p.brand,
    cat?.name,
    parent?.name,
    ...(CATEGORY_KEYWORDS[cat?.slug ?? ""] ?? []),
    ...Object.values(p.attributes).map(String),
  ]
    .join(" ")
    .toLowerCase();
}

function inCategory(p: ProductDetail, slug: string): boolean {
  if (p.category?.slug === slug) return true;
  const parent = CATEGORIES.find((c) => c.id === p.category?.parent_id);
  return parent?.slug === slug;
}

export function searchProducts(params: SearchParams): Page<ProductSummary> {
  const tokens = params.q.toLowerCase().split(/\s+/).filter(Boolean);
  // Match on word prefixes so "phone" finds phones but not "headphones".
  const words = (s: string) => s.toLowerCase().split(/[^a-z0-9+'.]+/).filter(Boolean);
  const hit = (ws: string[], t: string) => ws.some((w) => w.startsWith(t));
  const scored = PRODUCTS.map((p) => {
    const text = words(searchableText(p));
    const title = words(p.canonical_title);
    let score = 0;
    for (const t of tokens) {
      if (!hit(text, t)) return null; // every word must match somewhere
      score += hit(title, t) ? 3 : 1;
      if (p.brand?.toLowerCase() === t) score += 2;
    }
    return { p, score };
  }).filter((x): x is { p: ProductDetail; score: number } => x !== null);

  const filtered = scored.filter(({ p }) => {
    if (params.category && !inCategory(p, params.category)) return false;
    if (params.min_price != null && p.best_price < params.min_price) return false;
    if (params.max_price != null && p.best_price > params.max_price) return false;
    return true;
  });

  const sorters: Record<string, (a: (typeof filtered)[number], b: (typeof filtered)[number]) => number> = {
    relevance: (a, b) => b.score - a.score || b.p.review_count - a.p.review_count,
    price_asc: (a, b) => a.p.best_price - b.p.best_price,
    price_desc: (a, b) => b.p.best_price - a.p.best_price,
    discount: (a, b) => (b.p.max_discount_percent ?? 0) - (a.p.max_discount_percent ?? 0),
    rating: (a, b) => (b.p.rating ?? 0) - (a.p.rating ?? 0) || b.p.review_count - a.p.review_count,
  };
  filtered.sort(sorters[params.sort ?? "relevance"] ?? sorters.relevance);

  const page = Math.max(1, params.page ?? 1);
  const start = (page - 1) * PAGE_SIZE;
  return {
    items: filtered.slice(start, start + PAGE_SIZE).map(({ p }) => toSummary(p)),
    total: filtered.length,
    page,
    page_size: PAGE_SIZE,
    pages: Math.ceil(filtered.length / PAGE_SIZE),
  };
}

// --------------------------------------------------------------------------- //
// Price history: deterministic random walk ending at today's price
// --------------------------------------------------------------------------- //
function seededRandom(seed: string): () => number {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

export function buildHistory(product: ProductDetail, days: number): PriceHistory {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const series = product.listings.map((listing) => {
    const rand = seededRandom(listing.id);
    const mrp = listing.mrp ?? listing.current_price;
    const floor = listing.current_price * 0.93;
    const ceiling = Math.min(mrp, listing.current_price * 1.22);
    let price = listing.current_price * (1.08 + rand() * 0.1);
    const points: PricePoint[] = [];
    for (let d = days; d >= 0; d--) {
      if (d === 0) {
        price = listing.current_price;
      } else {
        // Gentle drift towards today's price, converging smoothly over the last 10 days.
        const pull = d <= 10 ? 1 / (d + 1) : 0.6 / d;
        price += (listing.current_price - price) * pull + (rand() - 0.5) * listing.current_price * 0.015;
        if (d > 10 && rand() < 0.025) price *= 0.9; // flash sale dip
        price = Math.min(ceiling, Math.max(floor, price));
      }
      // Real stores price in whole rupees ending in 9 more often than not.
      const rupees = Math.round(price / 100 / 10) * 10 - 1;
      points.push({
        recorded_at: new Date(today.getTime() - d * DAY).toISOString(),
        price: d === 0 ? listing.current_price : rupees * 100,
        mrp: listing.mrp,
      });
    }
    return { listing_id: listing.id, platform: listing.platform, points };
  });

  let lowest: PricePoint | null = null;
  for (const s of series) for (const pt of s.points) if (!lowest || pt.price < lowest.price) lowest = pt;
  return {
    product_id: product.id,
    series,
    lowest_price: lowest?.price ?? null,
    lowest_at: lowest?.recorded_at ?? null,
  };
}

// --------------------------------------------------------------------------- //
// Api implementation
// --------------------------------------------------------------------------- //
function makeUser(fields: Partial<User>): User {
  return {
    id: uid(),
    email: null,
    phone: null,
    full_name: null,
    is_email_verified: false,
    is_phone_verified: false,
    ...fields,
  };
}

function signIn(user: User): User {
  save({ ...load(), user });
  return user;
}

function wishlistItems(): WishlistItem[] {
  return load().wishlist.map((w) => ({
    id: w.id,
    product: toSummary(findProduct(w.product_id)),
    target_price: w.target_price,
    created_at: w.created_at,
  }));
}

function alertItems(): PriceAlert[] {
  return load().alerts.map((a) => ({ ...a, product: toSummary(findProduct(a.product_id)) }));
}

export const mockApi: Api = {
  async search(params) {
    await delay();
    const query = params.q.trim();
    const store = load();
    if (store.user && query) {
      const history = [
        { id: uid(), query, created_at: now() },
        ...store.history.filter((h) => h.query.toLowerCase() !== query.toLowerCase()),
      ].slice(0, 50);
      save({ ...store, history });
    }
    return searchProducts(params);
  },

  async deals(limit = 8) {
    await delay(200);
    return [...PRODUCTS]
      .sort((a, b) => (b.max_discount_percent ?? 0) - (a.max_discount_percent ?? 0))
      .slice(0, limit)
      .map(toSummary);
  },

  async getProduct(id) {
    await delay();
    return findProduct(id);
  },

  async getPriceHistory(id, days) {
    await delay(300);
    return buildHistory(findProduct(id), days);
  },

  async getCategories() {
    await delay(100);
    return CATEGORIES;
  },

  async getPlatforms() {
    await delay(100);
    return PLATFORMS;
  },

  buyUrl: (listing) => listing.affiliate_url,

  auth: {
    async me() {
      await delay(120);
      return load().user;
    },
    async login(email) {
      await delay(500);
      const name = email.split("@")[0]!.replace(/[._]/g, " ");
      return signIn(makeUser({ email, full_name: name.replace(/\b\w/g, (c) => c.toUpperCase()), is_email_verified: true }));
    },
    async signup(fullName, email) {
      await delay(600);
      return signIn(makeUser({ email, full_name: fullName }));
    },
    async logout() {
      await delay(150);
      save({ ...load(), user: null });
    },
    async sendOtp(phone) {
      await delay(500);
      if (!/^\+91[6-9]\d{9}$/.test(phone)) {
        throw new ApiError(422, { code: "validation_error", message: "Enter a valid 10-digit Indian mobile number." });
      }
    },
    async verifyOtp(phone, code) {
      await delay(500);
      if (code !== MOCK_OTP) {
        throw new ApiError(400, { code: "invalid_otp", message: "That code is incorrect. Please try again." });
      }
      return signIn(makeUser({ phone, is_phone_verified: true }));
    },
    googleLoginUrl: () => "#mock-google",
  },

  wishlist: {
    async list() {
      requireUser();
      await delay();
      return wishlistItems();
    },
    async add(productId, targetPrice = null) {
      requireUser();
      await delay(200);
      findProduct(productId);
      const store = load();
      if (store.wishlist.some((w) => w.product_id === productId)) {
        throw new ApiError(409, { code: "conflict", message: "Already in your wishlist." });
      }
      const entry = { id: uid(), product_id: productId, target_price: targetPrice, created_at: now() };
      save({ ...store, wishlist: [entry, ...store.wishlist] });
      return wishlistItems().find((w) => w.id === entry.id)!;
    },
    async remove(id) {
      requireUser();
      await delay(150);
      const store = load();
      save({ ...store, wishlist: store.wishlist.filter((w) => w.id !== id) });
    },
  },

  alerts: {
    async list() {
      requireUser();
      await delay();
      return alertItems();
    },
    async create(productId, targetPrice) {
      requireUser();
      await delay(250);
      const product = findProduct(productId);
      if (targetPrice <= 0 || targetPrice >= product.best_price) {
        throw new ApiError(422, {
          code: "validation_error",
          message: "Target price must be below the current best price.",
        });
      }
      const store = load();
      const existing = store.alerts.find((a) => a.product_id === productId);
      const entry = existing
        ? { ...existing, target_price: targetPrice, is_active: true }
        : { id: uid(), product_id: productId, target_price: targetPrice, is_active: true, last_notified_at: null, created_at: now() };
      save({ ...store, alerts: [entry, ...store.alerts.filter((a) => a.id !== entry.id)] });
      return alertItems().find((a) => a.id === entry.id)!;
    },
    async update(id, patch) {
      requireUser();
      await delay(200);
      const store = load();
      const alerts = store.alerts.map((a) => (a.id === id ? { ...a, ...patch } : a));
      save({ ...store, alerts });
      const updated = alertItems().find((a) => a.id === id);
      if (!updated) throw new ApiError(404, { code: "not_found", message: "Alert not found." });
      return updated;
    },
    async remove(id) {
      requireUser();
      await delay(150);
      const store = load();
      save({ ...store, alerts: store.alerts.filter((a) => a.id !== id) });
    },
  },

  history: {
    async list() {
      requireUser();
      await delay(200);
      return load().history;
    },
    async remove(id) {
      requireUser();
      await delay(120);
      const store = load();
      save({ ...store, history: store.history.filter((h) => h.id !== id) });
    },
    async clear() {
      requireUser();
      await delay(150);
      save({ ...load(), history: [] });
    },
  },
};
