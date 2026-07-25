"""Database engine, session factory and schema bootstrap.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/db.py
==============================================================================

Роль коду в системі:
"Керує з'єднанням з базою даних" (Database Engine & Session Factory).

Призначення:
Ініціалізація SQLAlchemy Engine, створення фабрики сесій, автозавантаження
початкової SQL-схеми (schema.sql) та надання сесій для FastAPI.

Ключові паттерни та рішення розробника:
1. Захист від обривів з'єднань (pool_pre_ping=True):
   Автоматично перевіряє життєздатність сокета перед видачею з'єднання з пулу.
2. Виконання складних PL/pgSQL тригерів через Raw DBAPI:
   Скрипт `schema.sql` виконується через низькорівневий `raw_conn.cursor().execute(sql)`,
   що дозволяє обійти проблеми парсингу крапок з комою (;) в SQLAlchemy text().
3. FastAPI Dependency (`get_session`):
   Використання паттерну Yield забезпечує гарантоване закриття сесії 
   у блоці `finally` після завершення обробки HTTP-запиту.
4. Конфігурація сесій (expire_on_commit=False):
   Запобігає зайвим SELECT-запитам при зверненні до об'єктів після `commit()`.

Оцінка коду та покращення:
- Плюси: Грамотне вирішення проблеми з парсингом SQL-тригерів, безпечне закриття сесій.
- Мінуси: Синхронний драйвер БД у часі високих асинхронних навантажень може стати
  пляшковим горлом (у майбутньому варто розглядатися asyncpg / async_session).

"""
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
