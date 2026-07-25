"""Double-entry bookkeeping service.
==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/ledger.py
==============================================================================

Роль коду в системі:
"Веде бухгалтерський облік" (Ядро подвійного запису / Financial Accounting Engine).

Призначення:
Створення балансових транзакцій (Journal Lines), капіталізація витрат на товар,
автоматичний розрахунок собівартості (COGS) при продажу та формування оборотного балансу.

Ключові паттерни та рішення розробника:
1. Подвійний запис (Double-Entry Bookkeeping):
   Будь-який фінансовий факт створює проводку, де Сума Дебету = Сумі Кредиту.
   Валідується на рівні Python (`post_transaction`) та закріплюється тригером PostgreSQL.
2. Капіталізація витрат (Capitalization into Inventory):
   Ціна покупки, доставка та запчастини збільшують вартість активу (1200 Inventory).
   Витрати списуються на рахунок себевартості (5000 COGS) тільки під час продажу.
3. Matching Principle (Принцип відповідності):
   Продаж створює два записи: визнання доходу (Cash / Revenue) та списання
   накопичених витрат (COGS / Inventory), що дає точний розрахунок валового прибутку.
4. Обчислення природного балансу рахунків:
   Функція `account_balance` коригує знак залежно від типу рахунку (is_debit_positive).

Оцінка коду та покращення:
- Плюси: Повноцінна фінансова архітектура рівня ERP-систем, захист від помилок float.
- Мінуси: Невеликі N+1 проблеми в `trial_balance()` та повторні виклики `_account_map()`
  (варто додати кешування списку рахунків).

"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import FinancialTransaction, InventoryItem, JournalLine, LedgerAccount

# Account codes (see db/schema.sql seed)
CASH = "1010"
INVENTORY = "1200"
EQUITY = "3000"
REVENUE = "4000"
COGS = "5000"
MARKETING = "5100"


@dataclass
class Posting:
    code: str
    amount: float
    is_debit: bool
    inventory_item_id: int | None = None


def _account_map(session: Session) -> dict[str, LedgerAccount]:
    return {a.code: a for a in session.scalars(select(LedgerAccount)).all()}


def post_transaction(session: Session, description: str, postings: list[Posting]) -> FinancialTransaction:
    """Create a balanced transaction. Raises if debits != credits (DB trigger)."""
    debit = round(sum(p.amount for p in postings if p.is_debit), 2)
    credit = round(sum(p.amount for p in postings if not p.is_debit), 2)
    if debit != credit:
        raise ValueError(f"Unbalanced transaction: debit {debit} != credit {credit}")

    accounts = _account_map(session)
    tx = FinancialTransaction(description=description, created_at=dt.datetime.now(dt.timezone.utc))
    session.add(tx)
    session.flush()  # assign tx.id

    for p in postings:
        acct = accounts.get(p.code)
        if acct is None:
            raise ValueError(f"Unknown account code {p.code}")
        session.add(
            JournalLine(
                transaction_id=tx.id,
                account_id=acct.id,
                inventory_item_id=p.inventory_item_id,
                amount=p.amount,
                is_debit=p.is_debit,
            )
        )
    session.commit()  # trigger validates balance at commit
    return tx


# ---------------------------------------------------------------------------
# High level operations (the reseller accounting map)
# ---------------------------------------------------------------------------
def inject_capital(session: Session, amount: float) -> FinancialTransaction:
    """Owner funds the business: Debit Cash / Credit Equity."""
    return post_transaction(
        session,
        f"Capital injection {amount:.2f}",
        [Posting(CASH, amount, True), Posting(EQUITY, amount, False)],
    )


def record_purchase(session: Session, item: InventoryItem, amount: float) -> FinancialTransaction:
    """Buy product: Debit Inventory / Credit Cash."""
    return post_transaction(
        session,
        f"Purchase: {item.title}",
        [
            Posting(INVENTORY, amount, True, item.id),
            Posting(CASH, amount, False),
        ],
    )


def record_delivery(session: Session, item: InventoryItem, amount: float) -> FinancialTransaction:
    """Delivery capitalised into inventory cost: Debit Inventory / Credit Cash."""
    return post_transaction(
        session,
        f"Delivery capitalised: {item.title}",
        [
            Posting(INVENTORY, amount, True, item.id),
            Posting(CASH, amount, False),
        ],
    )


def record_parts(session: Session, item: InventoryItem, amount: float) -> FinancialTransaction:
    """Refurbishment parts capitalised: Debit Inventory / Credit Cash."""
    return post_transaction(
        session,
        f"Parts capitalised: {item.title}",
        [
            Posting(INVENTORY, amount, True, item.id),
            Posting(CASH, amount, False),
        ],
    )


def record_marketing(session: Session, item: InventoryItem | None, amount: float) -> FinancialTransaction:
    """Marketing spend: Debit Expense:Marketing / Credit Cash."""
    title = item.title if item else "general"
    return post_transaction(
        session,
        f"Marketing: {title}",
        [
            Posting(MARKETING, amount, True, item.id if item else None),
            Posting(CASH, amount, False),
        ],
    )


def record_sale(session: Session, item: InventoryItem, sale_price: float) -> FinancialTransaction:
    """Successful sale.

    Books two balanced transactions:
      1. Revenue:   Debit Cash / Credit Revenue:Sales
      2. COGS:      Debit Expense:ProductCost / Credit Inventory:Products
         (cost = capitalised inventory value for the item)
    Marks the item as sold.
    """
    cost = inventory_cost_of(session, item.id)
    # 1) revenue
    post_transaction(
        session,
        f"Sale revenue: {item.title}",
        [Posting(CASH, sale_price, True, item.id), Posting(REVENUE, sale_price, False, item.id)],
    )
    # 2) write off cost of goods sold
    tx = None
    if cost > 0:
        tx = post_transaction(
            session,
            f"COGS write-off: {item.title}",
            [Posting(COGS, cost, True, item.id), Posting(INVENTORY, cost, False, item.id)],
        )
    item.status = "sold"
    item.sold_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return tx


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
def inventory_cost_of(session: Session, item_id: int) -> float:
    """Capitalised cost of an item = sum of debits to Inventory for it."""
    inv = session.scalar(select(LedgerAccount).where(LedgerAccount.code == INVENTORY))
    if inv is None:
        return 0.0
    debit = session.scalar(
        select(func.coalesce(func.sum(JournalLine.amount), 0.0)).where(
            JournalLine.inventory_item_id == item_id,
            JournalLine.account_id == inv.id,
            JournalLine.is_debit.is_(True),
        )
    )
    return round(float(debit or 0.0), 2)


def account_balance(session: Session, code: str) -> float:
    """Signed balance of an account in its natural direction."""
    acct = session.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
    if acct is None:
        return 0.0
    debit = session.scalar(
        select(func.coalesce(func.sum(JournalLine.amount), 0.0)).where(
            JournalLine.account_id == acct.id, JournalLine.is_debit.is_(True)
        )
    ) or 0.0
    credit = session.scalar(
        select(func.coalesce(func.sum(JournalLine.amount), 0.0)).where(
            JournalLine.account_id == acct.id, JournalLine.is_debit.is_(False)
        )
    ) or 0.0
    balance = float(debit) - float(credit)
    return round(balance if acct.is_debit_positive else -balance, 2)


def trial_balance(session: Session) -> list[dict]:
    out = []
    for acct in session.scalars(select(LedgerAccount).order_by(LedgerAccount.code)).all():
        out.append(
            {
                "code": acct.code,
                "name": acct.name,
                "class": acct.class_,
                "balance": account_balance(session, acct.code),
            }
        )
    return out
