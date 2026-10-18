/**
 * API contract shared with the FastAPI backend (/api/v1).
 * Money is always an integer number of paise (₹1 = 100 paise), never a float.
 */

export type Paise = number;
export type ID = string;

export interface Platform {
  id: ID;
  name: string;
  slug: string;
  logo_url: string | null;
  base_url: string;
}

export interface Category {
  id: ID;
  name: string;
  slug: string;
  parent_id: ID | null;
}

export type OfferType = "bank" | "coupon" | "cashback" | "exchange" | "emi";

export interface Offer {
  type: OfferType;
  title: string;
  description?: string;
}

export interface Listing {
  id: ID;
  platform: Platform;
  title: string;
  url: string;
  affiliate_url: string;
  current_price: Paise;
  mrp: Paise | null;
  discount_percent: number | null;
  offers: Offer[];
  rating: number | null;
  review_count: number;
  in_stock: boolean;
  delivery_info: string | null;
  last_checked_at: string;
  is_best_deal: boolean;
}

/** One search result: a product grouped across stores. */
export interface ProductSummary {
  id: ID;
  canonical_title: string;
  brand: string | null;
  category: Category | null;
  image_url: string | null;
  best_price: Paise;
  highest_price: Paise;
  mrp: Paise | null;
  max_discount_percent: number | null;
  rating: number | null;
  review_count: number;
  store_count: number;
  best_platform: Platform;
}

export interface ProductDetail extends ProductSummary {
  model_number: string | null;
  ean: string | null;
  attributes: Record<string, string | number | boolean>;
  /** Sorted by price ascending; exactly one has is_best_deal=true. */
  listings: Listing[];
}

export interface PricePoint {
  recorded_at: string;
  price: Paise;
  mrp: Paise | null;
}

export interface PriceHistorySeries {
  listing_id: ID;
  platform: Platform;
  points: PricePoint[];
}

export interface PriceHistory {
  product_id: ID;
  series: PriceHistorySeries[];
  lowest_price: Paise | null;
  lowest_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type SortOption = "relevance" | "price_asc" | "price_desc" | "discount" | "rating";

export interface SearchParams {
  q: string;
  category?: string;
  /** paise */
  min_price?: number;
  /** paise */
  max_price?: number;
  sort?: SortOption;
  page?: number;
}

export interface User {
  id: ID;
  email: string | null;
  phone: string | null;
  full_name: string | null;
  is_email_verified: boolean;
  is_phone_verified: boolean;
}

export interface WishlistItem {
  id: ID;
  product: ProductSummary;
  target_price: Paise | null;
  created_at: string;
}

export interface PriceAlert {
  id: ID;
  product: ProductSummary;
  target_price: Paise;
  is_active: boolean;
  last_notified_at: string | null;
  created_at: string;
}

export interface SearchHistoryItem {
  id: ID;
  query: string;
  created_at: string;
}

export interface ApiErrorDetail {
  loc?: (string | number)[];
  message: string;
  type?: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: ApiErrorDetail[];
    request_id?: string;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: ApiErrorDetail[];
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody["error"]) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

/** Everything the UI needs from the backend. Implemented by the HTTP client and the mock. */
export interface Api {
  search(params: SearchParams): Promise<Page<ProductSummary>>;
  deals(limit?: number): Promise<ProductSummary[]>;
  getProduct(id: ID): Promise<ProductDetail>;
  getPriceHistory(id: ID, days: number): Promise<PriceHistory>;
  getCategories(): Promise<Category[]>;
  getPlatforms(): Promise<Platform[]>;
  /** Outbound link for a listing (server logs the click, then redirects to the affiliate URL). */
  buyUrl(listing: Listing): string;

  auth: {
    me(): Promise<User | null>;
    login(email: string, password: string): Promise<User>;
    signup(fullName: string, email: string, password: string): Promise<User>;
    logout(): Promise<void>;
    sendOtp(phone: string): Promise<void>;
    verifyOtp(phone: string, code: string): Promise<User>;
    googleLoginUrl(): string;
  };

  wishlist: {
    list(): Promise<WishlistItem[]>;
    add(productId: ID, targetPrice?: Paise | null): Promise<WishlistItem>;
    remove(id: ID): Promise<void>;
  };

  alerts: {
    list(): Promise<PriceAlert[]>;
    create(productId: ID, targetPrice: Paise): Promise<PriceAlert>;
    update(id: ID, patch: Partial<Pick<PriceAlert, "target_price" | "is_active">>): Promise<PriceAlert>;
    remove(id: ID): Promise<void>;
  };

  history: {
    list(): Promise<SearchHistoryItem[]>;
    remove(id: ID): Promise<void>;
    clear(): Promise<void>;
  };
}
