"""
==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: tests/test_ledger.py
==============================================================================

Роль коду в системі:
"Тестує фінансовий облік" (Double-Entry Ledger Integration Tests).

Призначення:
Інтеграційна перевірка бухгалтерських проводок, списання собівартості (COGS), 
капіталізації доставки та блокування незбалансованих транзакцій.

Ключові паттерни та рішення розробника:
1. Динамічний пропуск тестів (pytest.mark.skipif):
   Тести автоматично пропускаються, якщо реальний PostgreSQL недоступний.
2. Валідація цілісності подвійного запису:
   Перевіряє, що незбалансовані транзакції (дебет != кредит) кидають ValueError 
   та відхиляються тригером PostgreSQL.
3. Перевірка ланцюжка продажів (Matching Principle):
   Підтверджує, що продаж товару правильно нараховує виручку та списує 
   накопичену собівартість з рахунку інвентарю.
==============================================================================
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import ledger
from app.db import SessionLocal, engine, init_db
from app.models import InventoryItem


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()


def _new_item(session, title="Test item", buy=1000.0, market=1500.0) -> InventoryItem:
    item = InventoryItem(
        title=title,
        purchase_price=buy,
        estimated_market_price=market,
        status="purchased",
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(item)
    session.commit()
    return item


def test_purchase_moves_cash_to_inventory():
    with SessionLocal() as session:
        cash_before = ledger.account_balance(session, ledger.CASH)
        inv_before = ledger.account_balance(session, ledger.INVENTORY)
        item = _new_item(session)
        ledger.record_purchase(session, item, 1000.0)
        assert ledger.account_balance(session, ledger.CASH) == round(cash_before - 1000.0, 2)
        assert ledger.account_balance(session, ledger.INVENTORY) == round(inv_before + 1000.0, 2)


def test_unbalanced_transaction_rejected():
    with SessionLocal() as session:
        with pytest.raises(ValueError):
            ledger.post_transaction(
                session,
                "bad tx",
                [ledger.Posting(ledger.CASH, 100.0, True), ledger.Posting(ledger.EQUITY, 50.0, False)],
            )


def test_sale_books_revenue_and_cogs():
    with SessionLocal() as session:
        item = _new_item(session, title="Sellable", buy=1000.0, market=1500.0)
        ledger.record_purchase(session, item, 1000.0)
        ledger.record_delivery(session, item, 100.0)
        cost = ledger.inventory_cost_of(session, item.id)
        assert cost == 1100.0

        revenue_before = ledger.account_balance(session, ledger.REVENUE)
        cogs_before = ledger.account_balance(session, ledger.COGS)
        ledger.record_sale(session, item, 1450.0)

        session.refresh(item)
        assert item.status == "sold"
        assert ledger.account_balance(session, ledger.REVENUE) == round(revenue_before + 1450.0, 2)
        assert ledger.account_balance(session, ledger.COGS) == round(cogs_before + 1100.0, 2)
