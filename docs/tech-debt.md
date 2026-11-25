# Technical debt and deferred findings

Source: Milestone 3.1 code review and the independent re-review. Items stay **Open** until a
change fixes them *and* a regression test proves it. Do not mark anything resolved without that.

## Mandatory before the first live (real) store adapter

These are harmless while only mock adapters exist (mock errors carry no secrets and mock
responses are small), but must be fixed before any real store API is connected.

| ID | Severity | Where | Finding | Status |
|---|---|---|---|---|
| N2 | Medium | `app/adapters/logsafe.py` `redact` | Redaction misses: JSON-style secrets (`"api_key": "..."`, `"token": "..."`), a bare `affiliate=` parameter, camelCase credential keys (`AWSAccessKeyId=AKIA...`, value shorter than the long-token rule), and scheme-less URLs (`api.store.in/v1/items?q=...` keeps its path and query). | Open |
| A7 | Medium | `app/adapters/runner.py` `_validate` | No bound on records inspected. 100,000 records took ~2.0 s of synchronous validation **on the event loop**, after the per-store deadline, stalling every other request. Needs a response/record cap and/or bounded offloading. | Open |

## Technical debt (lower priority)

| ID | Severity | Where | Finding | Status |
|---|---|---|---|---|
| A6 | Low | `app/adapters/runner.py` `_run` | Deadlines rely on cooperative cancellation: an adapter that swallows `CancelledError` overran a 0.2 s deadline (1.22 s) and was reported `ok`. Document the adapter contract; optionally mark results exceeding the deadline as `timeout`. | Open |
| A10 | Low | `app/adapters/schemas.py` `StoreListing` | `attributes` dict is mutable inside a frozen model; attribute values are unbounded in length; `external_id` allows control characters. | Open |
| A11 | Low | `app/adapters/runner.py` `timeout_for` | An adapter class's own `timeout_seconds` is not capped at 30 s; an adapter-raised `TimeoutError` is reported as a deadline timeout. | Open |
| A12 | Low | `app/adapters/mock.py` `_relevance` | Brand ranking bonus only works for single-word brands; non-ASCII queries yield no tokens. | Open |
| A14 | Low | `app/core/config.py` | `cors_origins` keeps its own list parser, duplicating `_split_list`. | Open |

## Milestone 3.3 (search service) design limits

| ID | Severity | Where | Limit | Status |
|---|---|---|---|---|
| S1 | Low | `app/services/search.py` | At most 50 listings per store per query (`StoreSearchQuery.limit`), so very broad queries are capped (~300 listings before grouping). Fine for the mock catalogue; live stores need store-side pagination. | Open |
| S2 | Info | search vs. product detail | Text search uses the stores' current prices; browsing, `/deals`, product detail and history read the database. With live stores they can briefly differ until the refresh worker writes prices back. | Open |
| S3 | Info | `app/schemas/search.py` | `q` was required. | Resolved in 3.5: no `q` = browse stored listings; `/deals` added. |
| S4 | Info | `app/services/search.py` | Store listings with no database row are left out (`unresolved_count`); showing them needs Phase 4 matching. Never non-zero with the mock adapters. | Open |

## Phase 5 (authentication) design limits

| ID | Severity | Where | Limit | Status |
|---|---|---|---|---|
| P1 | Low | `app/core/security.py` | Password blocklist is a short built-in list; no breached-password (HIBP k-anonymity) check. | Open |
| P2 | Info | access tokens | A stolen access token stays valid until it expires (15 min); logout clears cookies and revokes the refresh family. Tokens carry `sid` so 5.8 can add a per-request revocation check if needed. | Open (5.8) |
| P3 | Info | deployment | Cookies assume same-origin (frontend proxies `/api`) or same-site (subdomain). `frontend/vercel.json` has no `/api` proxy yet; it must be added (or a subdomain used) before production login works. | Open |
| P4 | Info | `/auth/signup` | The required duplicate-email message ("An account with this email already exists. Please log in.") confirms an email is registered. Accepted per the Phase 5 spec; mitigated by the signup rate limit. | Accepted |
| P5 | Info | `/auth/signup` | Accounts can sign in before verifying their email (verification is Milestone 5.4). | Open (5.4) |
| P6 | Low | `refresh_tokens` | Expired and revoked token rows are never deleted. Add a cleanup job (Milestone 6.6). | Open (6.6) |
| R1 | Info | `app/services/rate_limit.py` | Fixed windows allow up to 2x the limit across a boundary. When Redis is down, limits are per worker process. | Open |

## Milestone 3.5 (public API) design limits

| ID | Severity | Where | Limit | Status |
|---|---|---|---|---|
| B1 | Low | `app/repositories/catalog.py` `browse_products` | Browsing and `/deals` load every product in the selection (2 queries) and sort/page in memory. Fine for the curated catalogue (20 products); move aggregation, sorting and paging into SQL before the catalogue grows to thousands. | Open |
| B2 | Info | `app/services/catalog.py` | Product detail is cached for `CACHE_TTL_SECONDS`; a platform deactivated or a listing changed in the database shows up after expiry (see C1). | Open |
| B3 | Info | `/products/{id}` | A product whose listings are all hidden (inactive store or unsafe URL) returns 404, because the page has no price to show. | Open |
| B4 | Info | `affiliate_url` | Points at `/api/v1/go/{listing_id}`, which is implemented in Milestone 3.6; until then the link returns 404. | Open (3.6) |

## Milestone 3.4 (Redis caching) design limits

| ID | Severity | Where | Finding | Status |
|----|----------|-------|---------|--------|
| C1 | Info | `app/services/cache.py` | Search results can be up to `CACHE_TTL_SECONDS` (30 min) old, including per-store `stores[]` status. `SearchCache.invalidate()` exists but nothing calls it yet; price-refresh jobs should call it when they land. | Open |
| C2 | Info | `app/services/cache.py` | Single-flight is per process. With several workers, each may query the stores once for the same new search. | Open |
| C3 | Info | `app/services/cache.py` | Cache keys lowercase and collapse whitespace in the query. Correct for the mock adapters; re-check when a live store API treats case as significant. | Open |
| C5 | Low | `app/services/cache.py` | The search generation counter (`search:gen`) is an ordinary key. If LRU evicts it after an `invalidate()`, the generation falls back to 0 and older generation-0 entries could be served until their TTL ends. No impact today (nothing calls `invalidate()` yet). | Open |
| C4 | Low | Local dev | Memurai Developer is a development-only edition (it shuts down after 10 days of uptime; `Restart-Service Memurai` from an elevated shell brings it back). Production needs real Redis. The app fails open if it stops. | Open |

## Notes carried from fixed items (not defects today)

- **A2:** scheme-less redirect values (`?u=evil.com`) pass by design (blocking them would block
  normal search terms); the exact host allowlist still applies. A path containing `//` is now
  rejected, which could reject a rare legitimate store URL.
- **A5 (Milestone 3.x, `/go`):** stored URLs bypass the adapter runner, so `/go/{listing_id}` must
  re-run `url_problem(url, store.allowed_hosts)` at redirect time. Affiliate-network wrapper links
  (Cuelinks, EarnKaro) embed the target URL, so the affiliate step must not apply the
  embedded-redirect rule to the generated `affiliate_url` as-is.
- **A3:** product-ID comparison is exact and case-sensitive.
- **A8:** other timeout settings (`health_check_timeout_seconds`, `db_*_timeout_seconds`) still
  accept booleans (outside A8's scope).
- **A9:** the "shutdown" log line is skipped when a cleanup step raises.

## Resolved (with regression tests)

- **5.1 finding:** settings validation errors echoed the rejected value, so a too-short
  `AUTH_SECRET_KEY` or a malformed `DATABASE_URL`/`REDIS_URL` would print its secret in the
  startup error. Fixed with `hide_input_in_errors=True`; covered by
  `tests/test_config.py::test_settings_errors_never_echo_values`.

A1, A2, A3, A4, A8, A9 (Milestone 3.1 review fixes) and N1 (unprintable exceptions crashing
logging), each covered by tests under `tests/adapters/`, `tests/test_config.py` and
`tests/test_lifespan.py`.

A13 (README status line) - updated in Milestone 3.3 (documentation-only; no test applies).
