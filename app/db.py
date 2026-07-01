"""Database engine, session factory and schema bootstrap."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_settings = get_settings()

engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def init_db() -> None:
    """Apply the SQL schema (tables, trigger, seed accounts). Idempotent."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        # execute the whole script in one go; psycopg supports multi-statement.
        conn.execute(text("SELECT 1"))
        # SQLAlchemy's text() splits on ; poorly for functions, so use the raw
        # DBAPI connection to run the full script verbatim.
        raw = conn.connection
        with raw.cursor() as cur:
            cur.execute(sql)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
