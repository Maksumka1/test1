"""Pytest bootstrap: route integration tests to a dedicated test database.

Ensures the ledger integration tests never pollute the development/demo
database. The test DB name is the configured one suffixed with ``_test`` and is
created automatically if missing (when PostgreSQL is reachable).
"""
from __future__ import annotations

import os

import psycopg


def _derive_test_url(url: str) -> tuple[str, str, str]:
    """Return (admin_dsn, test_dbname, test_sqlalchemy_url)."""
    # url like postgresql+psycopg://user:pass@host:port/dbname
    scheme_rest = url.split("://", 1)[1]
    creds_host, dbname = scheme_rest.rsplit("/", 1)
    test_db = f"{dbname}_test"
    admin_dsn = f"postgresql://{creds_host}/postgres"
    test_url = url.rsplit("/", 1)[0] + f"/{test_db}"
    return admin_dsn, test_db, test_url


def _ensure_test_db(url: str) -> str:
    admin_dsn, test_db, test_url = _derive_test_url(url)
    try:
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{test_db}"')
    except Exception:
        # PostgreSQL unreachable -> leave URL as-is; DB tests will self-skip.
        return url
    return test_url


_base_url = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://arbitrage:arbitrage@localhost:5432/arbitrage"
)
os.environ["DATABASE_URL"] = _ensure_test_db(_base_url)
