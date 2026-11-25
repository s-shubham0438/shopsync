"""Create the development database role and database (idempotent).

Reads the target user / password / database name from DATABASE_URL (via app settings) and
connects to the server's maintenance database as a superuser to create them.

Usage:
    python scripts/create_dev_db.py --superuser-password-file .secrets/postgres-superuser.txt
    # also create the test database (same owner):
    python scripts/create_dev_db.py --superuser-password-file <file> --database shopsync_test
    # or: set PG_SUPERUSER_PASSWORD and run without arguments
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _quote_ident(name: str) -> str:
    # Identifiers can't be bound as parameters; restrict to a safe charset instead.
    if not _IDENT.fullmatch(name):
        raise SystemExit(f"Refusing unsafe identifier: {name!r}")
    return f'"{name}"'


def _read_password(args: argparse.Namespace) -> str:
    if args.superuser_password_file:
        for line in Path(args.superuser_password_file).read_text().splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
        return Path(args.superuser_password_file).read_text().strip()
    password = os.environ.get("PG_SUPERUSER_PASSWORD")
    if not password:
        raise SystemExit("Provide --superuser-password-file or set PG_SUPERUSER_PASSWORD")
    return password


async def main(args: argparse.Namespace) -> None:
    url = make_url(get_settings().sqlalchemy_url)
    role, password, database = url.username, url.password, args.database or url.database
    if not role or not password or not database:
        raise SystemExit("DATABASE_URL must include a username, password and database name")

    conn = await asyncpg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=args.superuser,
        password=_read_password(args),
        database="postgres",
    )
    try:
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
            print(f"role {role!r} exists")
        else:
            # Parameters aren't allowed in utility statements; quote_literal escapes the password.
            literal = await conn.fetchval("SELECT quote_literal($1)", password)
            await conn.execute(f"CREATE ROLE {_quote_ident(role)} LOGIN PASSWORD {literal}")
            print(f"created role {role!r}")

        if await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database):
            print(f"database {database!r} exists")
        else:
            owner = _quote_ident(role)
            await conn.execute(
                f"CREATE DATABASE {_quote_ident(database)} OWNER {owner} ENCODING 'UTF8'"
            )
            print(f"created database {database!r} owned by {role!r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--superuser", default="postgres")
    parser.add_argument("--superuser-password-file")
    parser.add_argument(
        "--database", help="database name to create (default: the one in DATABASE_URL)"
    )
    asyncio.run(main(parser.parse_args()))
