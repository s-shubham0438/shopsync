# ShopSync API

Backend for a price comparison platform: search a product and compare prices, offers and
ratings across Indian e-commerce stores (Amazon, Flipkart, Myntra, Ajio, …).

FastAPI · PostgreSQL 16 · SQLAlchemy 2 (async) · Alembic · Redis · Python 3.14

> Status: **Phase 2 (database)**. Redis, worker and scheduler setup is added in later phases;
> the full guide is completed in Phase 8.

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

**Install.** Use the official installer from postgresql.org (EDB, Windows x64), or any PostgreSQL 16
build that includes the `pg_trgm` contrib extension. On this dev machine PostgreSQL lives in the
user profile (no Windows service), managed with:

```powershell
.\scripts\db.ps1 start     # also: stop | restart | status
```

(`$env:PG_BIN` / `$env:PG_DATA` override the default binary and data locations.)

**Create the role and databases** (idempotent; reads user/password/db name from `DATABASE_URL`):

```powershell
python scripts\create_dev_db.py --superuser-password-file .secrets\postgres-superuser.txt
python scripts\create_dev_db.py --superuser-password-file .secrets\postgres-superuser.txt --database shopsync_test
```

The superuser password file is git-ignored. You can also set `PG_SUPERUSER_PASSWORD` instead.

**Migrate and seed:**

```powershell
alembic upgrade head          # create/upgrade the schema
python -m app.db.seed         # 6 stores, 9 categories, 20 products, ~90 days of price history
```

Every schema change goes through Alembic: edit models in `app/models/`, then
`alembic revision --autogenerate -m "describe change"`, **review the file**, and `alembic upgrade head`.

### Schema notes

- **IDs:** UUIDv7 (`uuid.uuid7()`). Unique like v4, but time-ordered, so indexes stay compact.
- **Money:** `BIGINT` paise, never floats. `listings.discount_percent` is a generated column
  computed from price and MRP.
- **Matching:** `pg_trgm` GIN indexes on lowercased product/listing titles (fuzzy search),
  a unique partial index on `products.ean`, and an index on `(lower(brand), lower(model_number))`.
- **Auth:** emails are unique case-insensitively; phones are E.164. Refresh tokens store only a
  SHA-256 hash, with `family_id`/`replaced_by_id` for rotation and reuse detection.

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
- `VITE_USE_MOCKS=false` calls the real API. In dev, Vite proxies `/api` to `http://localhost:8000`,
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
