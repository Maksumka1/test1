"""SQLAlchemy ORM models mapping the arbitrage schema.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/models.py
==============================================================================

Роль коду в системі:
"Визначає ORM-структуру бази даних" (SQLAlchemy Data Domain Models).

Призначення:
Опис таблиць PostgreSQL для подвійного бухгалтерського обліку, складського інвентарю,
арбітражних кампаній та парсингу оголошень OLX за допомогою SQLAlchemy 2.0.

Ключові паттерни та рішення розробника:
1. Синтаксис SQLAlchemy 2.0 (`Mapped` & `mapped_column`):
   Забезпечує точну статичну типізацію та автодоповнення типів даних у IDE.
2. Фінансова точність через `Numeric(12, 2)`:
   Використання точних десяткових типів замість двійкового `Float` для запобігання
   помилкам округлення в грошових обчисленнях.
3. Глобальні унікальні ідентифікатори (UUIDv4):
   Таблиця `FinancialTransaction` використовує UUID як первинний ключ для 
   захисту фінансових записів від перебору та забезпечення унікальності.
4. Каскадне управління зв'язками:
   Використання `cascade="all, delete-orphan"` та унікального обмеження 
   `UniqueConstraint("campaign_id", "olx_offer_id")` гарантує цілісність даних.

Оцінка коду та покращення:
- Плюси: Сучасний стиль ORM, строга фінансова математика, безпечна робота з UTC-часом.
- Мінуси: Анотація `Mapped[float]` для полів `Numeric` (краще використовувати `decimal.Decimal`
  для повної сумісності типів).

"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    class_: Mapped[str] = mapped_column("class", String(20))
    is_debit_positive: Mapped[bool] = mapped_column(Boolean)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    olx_offer_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    purchase_price: Mapped[float] = mapped_column(Numeric(12, 2))
    estimated_market_price: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(50), default="purchased")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    sold_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class FinancialTransaction(Base):
    __tablename__ = "financial_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_transactions.id", ondelete="CASCADE")
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    is_debit: Mapped[bool] = mapped_column(Boolean)

    transaction: Mapped[FinancialTransaction] = relationship(back_populates="lines")
    account: Mapped[LedgerAccount] = relationship()


class SearchCampaign(Base):
    __tablename__ = "search_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="training")
    market_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    min_discount: Mapped[float] = mapped_column(Numeric(5, 2), default=20.0)
    weight_kg: Mapped[float] = mapped_column(Numeric(6, 2), default=1.0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("campaign_id", "olx_offer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("search_campaigns.id", ondelete="CASCADE"))
    olx_offer_id: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    url: Mapped[str | None] = mapped_column(String(500))
    seller_account_age_days: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    discount: Mapped[float | None] = mapped_column(Numeric(5, 2))
    net_profit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    is_deal: Mapped[bool] = mapped_column(Boolean, default=False)
    risks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
