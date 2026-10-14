# ShopSync API

Backend for a price comparison platform: search a product and compare prices, offers and
ratings across Indian e-commerce stores (Amazon, Flipkart, Myntra, Ajio, …).

FastAPI · PostgreSQL 16 · SQLAlchemy 2 (async) · Alembic · Redis · Python 3.14

> Status: **Phase 1 (project setup)**. The full setup guide (PostgreSQL/Redis install,
> migrations, worker and scheduler) is completed in Phase 8.

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

## Checks

```powershell
pytest            # tests (no DB/Redis needed for Phase 1)
ruff check .      # lint
ruff format .     # format
mypy app          # type-check (strict)
```

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
