"""Run the API against the *test* database for manual UI testing (sign-ups, logins, ...),
so throwaway accounts never land in the development database.

    python scripts/dev_backend_testdb.py            # http://localhost:8000

Uses TEST_DATABASE_URL (default: shopsync_test on localhost), migrates it to head and seeds the
catalogue (idempotent). Everything else (Redis, AUTH_SECRET_KEY, ...) comes from .env as usual.
Refuses to run against the development database. Note: the pytest suite rebuilds shopsync_test,
so accounts created here disappear on the next test run.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")  # Windows Smart App Control

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://shopsync:shopsync@localhost:5432/shopsync_test"
)


def main() -> None:
    from sqlalchemy.engine import make_url

    if make_url(TEST_DATABASE_URL).database != "shopsync_test":
        sys.exit("Refusing to run: TEST_DATABASE_URL must point at the shopsync_test database.")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # environment beats .env
    # Both dev frontends (web on :5173, web-real on :5174) may call this API.
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")

    import uvicorn
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings
    from app.db.seed import run_seed
    from app.db.session import create_engine, create_sessionmaker

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")

    async def seed() -> None:
        engine = create_engine(get_settings())
        try:
            async with create_sessionmaker(engine)() as session:
                await run_seed(session)
        finally:
            await engine.dispose()

    asyncio.run(seed())
    print("API on http://localhost:8000 using shopsync_test (dev database untouched)")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
