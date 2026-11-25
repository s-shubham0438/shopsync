# ShopSync API

Backend for a price comparison platform: search a product and compare prices, offers and
ratings across Indian e-commerce stores (Amazon, Flipkart, Myntra, Ajio, …).

FastAPI · PostgreSQL 16 · SQLAlchemy 2 (async) · Alembic · Redis · Python 3.14

> Status: **Phase 3 in progress.** Done: 3.1 store-adapter architecture, 3.2 six mock stores,
> 3.3 search service, 3.4 Redis caching, 3.5 public catalogue API. Still open: 3.6 affiliate
> redirects (`/go/{listing_id}`), 3.7 verification. Phase 4 (matching) skipped for now.
> **Phase 5 (auth) in progress:** 5.1 security foundation and 5.2 email/password auth done;
> next 5.3 frontend integration.
> Known follow-ups: [`docs/tech-debt.md`](docs/tech-debt.md).

## Quick start (Windows, PowerShell)

```powershell
# 1. Virtual environment (Python 3.14)
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependencies (app + dev tools)
python -m pip install --upgrade pip
pip install -e . --group dev

# 3. Configuration
Copy-Item .env.example .env   # then edit values

# 4. Run the API
uvicorn app.main:app --reload
```

With [uv](https://docs.astral.sh/uv/) instead: `uv sync` then `uv run uvicorn app.main:app --reload`.

- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/api/v1/openapi.json
- Health: http://localhost:8000/api/v1/health

The API starts even if PostgreSQL/Redis are not running. `/api/v1/health` then returns
`503` with `"status": "degraded"` and shows which dependency is unreachable.

## Database (PostgreSQL 16)

**Install.** Official PostgreSQL 16 for Windows (EDB installer, or
`winget install PostgreSQL.PostgreSQL.16`) with the command-line tools; it includes `pg_trgm`.
It runs as the Windows service `postgresql-x64-16` and **starts automatically** with Windows, so
there is nothing to start manually. It accepts local connections only (`listen_addresses = 'localhost'`).

```powershell
.\scripts\db.ps1            # status: service state + "accepting connections" check
.\scripts\db.ps1 backup     # new timestamped pg_dump in %USERPROFILE%\ShopSync-backups (never overwrites)
.\scripts\db.ps1 restart    # also: start | stop (elevated PowerShell only; rarely needed)
```

`psql`, `pg_dump` and `pg_restore` live in `C:\Program Files\PostgreSQL\16\bin` (not on PATH by
default). `$env:PG_BIN` and `$env:SHOPSYNC_BACKUP_DIR` override the tool and backup folders.
The backup reads `DATABASE_URL` from the environment or `.env` and never prints the password.

**Create the role and databases** (idempotent; reads user/password/db name from `DATABASE_URL`):

```powershell
python scripts\create_dev_db.py --superuser-password-file .secrets\postgres-superuser.txt
python scripts\create_dev_db.py --superuser-password-file .secrets\postgres-superuser.txt --database shopsync_test
```

The superuser password file is git-ignored. You can also set `PG_SUPERUSER_PASSWORD` instead.

**Migrate and seed:**

```powershell
python -m alembic upgrade head   # create/upgrade the schema
python -m app.db.seed         # 6 stores, 9 categories, 20 products, ~90 days of price history
```

Every schema change goes through Alembic: edit models in `app/models/`, then
`python -m alembic revision --autogenerate -m "describe change"`, **review the file**, and
`python -m alembic upgrade head`. (`python -m alembic` also works where the `alembic.exe` launcher
is blocked, e.g. by Windows Smart App Control.)

### Schema notes

- **IDs:** UUIDv7 (`uuid.uuid7()`). Unique like v4, but time-ordered, so indexes stay compact.
- **Money:** `BIGINT` paise, never floats. `listings.discount_percent` is a generated column
  computed from price and MRP.
- **Matching:** `pg_trgm` GIN indexes on lowercased product/listing titles (fuzzy search),
  a unique partial index on `products.ean`, and an index on `(lower(brand), lower(model_number))`.
- **Auth:** emails are unique case-insensitively; phones are E.164. Refresh tokens store only a
  SHA-256 hash, with `family_id`/`replaced_by_id` for rotation and reuse detection.

## Store adapters (`app/adapters/`)

Every store integration implements one interface (`StoreAdapter`: `search()`, `get_product()`,
`aclose()`) and returns normalised `StoreListing`s, which are independent of the database models.
Money is integer paise.

- **Mock first.** `STORE_ADAPTER_MODE=mock` (default) runs one `MockStoreAdapter` per store over
  the seed catalogue, with the same external ids as the seeded `listings` rows.
- **Parallel, isolated.** `AdapterRunner` queries all enabled stores concurrently. Each store has its
  own deadline (`STORE_ADAPTER_TIMEOUTS` override, then the adapter's default, then
  `STORE_ADAPTER_TIMEOUT_SECONDS`). A slow or failing store yields a `timeout`/`error` result for
  that store only, and results are marked partial. Client disconnects cancel every store call.
- **Untrusted output.** Each record is checked in order and the first acceptable one wins: right
  store, safe URL (HTTPS, exact host allowlist from `app/core/stores.py`, no credentials, no
  embedded redirect URLs), then no duplicate `external_id`. Rejections are logged as
  `adapter_listing_rejected` with a reason (never the URL).
- **Strict config.** Unknown or duplicate stores, out-of-range timeouts and a non-zero
  `MOCK_ADAPTER_FAILURE_RATE` in production are rejected when settings load.
  `STORE_ADAPTER_MODE=live` with no live adapter refuses to start.
- **Adding a real store** (official/affiliate API only, never scraping): implement `StoreAdapter`,
  map the API response to `StoreListing` (`parse_records` skips bad records), raise `AdapterError`
  subclasses for expected failures, read credentials from settings (never hard-code them), and
  register it in `LIVE_ADAPTERS` in `app/adapters/registry.py`. **Before the first live adapter**,
  resolve the mandatory items in [`docs/tech-debt.md`](docs/tech-debt.md) (log redaction gaps N2,
  oversized-response protection A7).

## Search service (`app/services/search.py`)

`SearchService.search(SearchRequest) -> SearchResponse`, served as `GET /api/v1/search`.
Without `q` it **browses** stored listings instead (no store calls), optionally within a
category; the steps below are for text search:

1. Unknown `category` -> `422 invalid_filter` before any store is queried.
2. All enabled stores are queried in parallel through `AdapterRunner` (up to 50 listings per
   store); price filters are not sent to stores, so every product's full set of offers is known.
3. Each store listing is resolved to the database by (platform slug, external id) in **one**
   query; listings with no row are left out and counted in `unresolved_count` (grouping unknown
   listings needs Phase 4 matching).
4. Listings are grouped by their **existing** `product_id` links (no matching algorithm), then
   filtered by category (including child categories) and by each product's best in-stock price,
   sorted (`relevance`, `price_asc`, `price_desc`, `discount`, `rating`; ties broken by product id
   so pages are stable) and paginated (`page_size` 1-50).
5. Some stores failing -> results with `partial: true` and per-store `stores[]` status; every
   store failing -> `503 service_unavailable`.

Database access is a fixed 2-3 queries per search (`app/repositories/catalog.py`), never one per
result. Result items match the frontend's `ProductSummary` contract. Money is integer paise.

## Public API (no login needed)

| Endpoint | What it returns |
|---|---|
| `GET /api/v1/search?q=&category=&min_price=&max_price=&sort=&page=&page_size=` | Products grouped across stores. With `q`: live store search (cached). Without `q`: browse stored listings. Prices in paise. |
| `GET /api/v1/deals?limit=8` | In-stock discounted products, biggest discount first (`limit` 1-24). |
| `GET /api/v1/products/{id}` | Product detail with every store listing: in-stock first, then cheapest; exactly one `is_best_deal`. `X-Cache` header shows Redis hit/miss. |
| `GET /api/v1/products/{id}/price-history?days=30` | Per-store price series, oldest first, plus the lowest price in the window (`days` 1-365). |
| `GET /api/v1/categories` | All categories (flat, with `parent_id`). Cached by browsers for 5 minutes. |
| `GET /api/v1/platforms` | Active stores. Cached by browsers for 5 minutes. |

- Errors use the standard envelope: bad parameters return `422 validation_error`, an unknown
  category `422 invalid_filter`, an unknown product `404 not_found`, and no store responding `503`.
- Store URLs are re-checked against each store's host allowlist before they are returned; a
  listing that fails is hidden and logged. Listings on inactive platforms are hidden everywhere.
- Buy links (`affiliate_url`) point at ShopSync's `/api/v1/go/{listing_id}` (Milestone 3.6).
- Every endpoint runs a fixed 1-3 database queries (tests count them).
- Response shapes match `frontend/src/api/types.ts` (checked by tests). Auth, wishlist, alerts
  and search history endpoints arrive in Phases 5-6.

## Authentication (Phase 5)

| Endpoint | What it does |
|---|---|
| `POST /api/v1/auth/signup` `{full_name, email, password}` | Creates the account and signs in (201). Duplicate email (any case): 409 "An account with this email already exists. Please log in." |
| `POST /api/v1/auth/login` `{email, password}` | Signs in (200). Every failure is the same 401 "Incorrect email or password." |
| `POST /api/v1/auth/refresh` | Rotates the session cookies (204). Failure: 401 and the cookies are cleared. |
| `POST /api/v1/auth/logout` | Ends this session and clears the cookies (204, always). |
| `GET /api/v1/auth/me` | The signed-in user, or 401. |

- Bodies never contain tokens or password hashes; responses are `Cache-Control: no-store`.
- Each login starts a session (a refresh-token family). Refreshing rotates the token; presenting
  an old one after `REFRESH_REUSE_GRACE_SECONDS` (10 s) is treated as theft and ends that session
  everywhere. At most `AUTH_MAX_SESSIONS` (10) sessions per user; the oldest ends first.
- Rate limits: login 50/IP and 10/account per 15 min, signup 10/IP per hour, refresh 60/IP per
  15 min (429 with `Retry-After`).

Building blocks (5.1):

- **Passwords:** Argon2id (`argon2-cffi`), hashed off the event loop. Unknown accounts still run a
  full Argon2 check, so timing doesn't reveal which emails exist. Policy: 8-128 characters, not a
  common password, not the email name (no composition rules).
- **Sessions:** a 15-minute access JWT (HS256, `AUTH_SECRET_KEY`) in the `ss_access` cookie, and
  a random 256-bit refresh token in `ss_refresh` (sent only to `/api/v1/auth`; only its SHA-256 is
  stored). Both cookies are `HttpOnly`, `Secure`, `SameSite=Lax`.
- **Who is calling:** routes use `CurrentUser` (401 if not signed in) or `OptionalUser`. The user
  always comes from the verified token, never from request data. Inactive users are rejected.
- **CSRF:** besides SameSite, any POST/PUT/PATCH/DELETE carrying an auth cookie must come from an
  allowed origin (`CORS_ORIGINS` or the API itself), else `403 csrf_failed`.
- **Rate limiting:** Redis fixed windows keyed by HMAC'd IP/account; falls back to in-process
  counters (never opens up) when Redis is down.
- **Production refuses to start** without a strong `AUTH_SECRET_KEY`, with `COOKIE_SECURE=false`,
  or with non-https `CORS_ORIGINS`.
- **Deployment:** cookies need the API on the same origin (proxy `/api` from the frontend host)
  or the same site (e.g. `api.shopsync.in`). Cross-site hosting is not supported.

## Caching (Redis / Memurai)

**Local Redis on Windows:** [Memurai](https://www.memurai.com/) Developer (Redis-compatible),
running as the Windows service `Memurai` on `127.0.0.1:6379` only, with a password and a 256 MB
LRU memory cap. Put the password in `REDIS_URL` in `.env` (`redis://:<password>@localhost:6379/0`);
logs always mask it. The Developer edition shuts down after 10 days of uptime; restart the service.

`app/services/cache.py`:

- **Search** caches everything before price filtering, sorting and paging, keyed by the normalised
  query (case/whitespace-insensitive), category and store configuration. One entry serves every
  sort order, page and price range; a hit makes no store or database calls.
  `CACHE_TTL_SECONDS` (30 min) normally, `CACHE_PARTIAL_TTL_SECONDS` (60 s) when some stores
  failed. Errors (503, unknown category) are never cached. Identical concurrent searches in one
  process share a single store query.
- **Fail-open.** Each Redis call has a `CACHE_OP_TIMEOUT_SECONDS` (0.25 s) deadline. Any Redis error
  means "uncached": search still works, Redis is skipped for `CACHE_FAILURE_BACKOFF_SECONDS`, and
  one `cache_unavailable` warning is logged per window. `CACHE_ENABLED=false` turns it off.
- **Responses** carry `cache`: `hit`, `miss` or `bypass` (disabled/unavailable).
- **Safety.** JSON only (no pickle). Keys are `shopsync:v1:…` with a SHA-256 digest instead of
  the query text. Entries that fail to parse are deleted and recomputed. Entries over
  `CACHE_MAX_ENTRY_BYTES` are not stored. `SearchCache.invalidate()` makes every search entry stale.
- **Product details** (`ProductCache`) cache `GET /products/{id}` for `CACHE_TTL_SECONDS`.
  Browsing, deals, history, categories and platforms read the database directly.

Integration tests use Redis **db 15** (`TEST_REDIS_URL`, or `REDIS_URL` with the db switched to
15), never db 0, and skip if Redis is unreachable.

## Checks

```powershell
pytest            # unit + integration tests (integration tests skip if shopsync_test is unreachable)
ruff check .      # lint
ruff format .     # format
mypy app tests scripts   # type-check (strict)
```

## Frontend (`frontend/`)

React 19 + TypeScript + Tailwind CSS v4 (Vite), TanStack Query, React Router.

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev        # http://localhost:5173
npm test           # unit tests (vitest)
npm run build      # typecheck + production build
```

- `VITE_USE_MOCKS=true` (default) runs the whole UI on built-in demo data, with no backend needed.
  Demo phone OTP code: `123456`.
- `VITE_USE_MOCKS=hybrid` uses the real backend for what is built so far (`/health`, shown as a status dot in the footer) and demo data for everything else.
- `VITE_USE_MOCKS=false` calls the real API (every endpoint must exist). In dev, Vite proxies `/api` to `http://localhost:8000`,
  so auth cookies stay same-origin.
- The API contract the UI expects lives in `frontend/src/api/types.ts` (money is always integer paise).

## API conventions

- All endpoints are under `/api/v1`.
- **Success** responses return the resource directly. Lists are paginated as
  `{"items": [...], "total", "page", "page_size", "pages"}`.
- **Errors** always use one envelope:
  ```json
  {"error": {"code": "not_found", "message": "Product not found.", "request_id": "…"}}
  ```
  Validation errors (`422`) add `details: [{"loc": [...], "message": "...", "type": "..."}]`.
- Every response carries an `X-Request-ID` header (a valid incoming one is reused), which
  also appears in every log line for that request.
