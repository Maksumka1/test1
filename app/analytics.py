"""Dashboard analytics and strategic metrics."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ledger
from .config import get_settings
from .models import FinancialTransaction, InventoryItem, JournalLine, LedgerAccount, SearchCampaign

IN_STOCK_STATUSES = ("purchased", "in_transit", "in_stock", "refurbishing")


def _sum_lines_by_class(session: Session, class_: str, is_debit: bool, since: dt.datetime | None) -> float:
    stmt = (
        select(func.coalesce(func.sum(JournalLine.amount), 0.0))
        .join(LedgerAccount, JournalLine.account_id == LedgerAccount.id)
        .where(LedgerAccount.class_ == class_, JournalLine.is_debit.is_(is_debit))
    )
    if since is not None:
        stmt = stmt.join(
            FinancialTransaction, JournalLine.transaction_id == FinancialTransaction.id
        ).where(FinancialTransaction.created_at >= since)
    return float(session.scalar(stmt) or 0.0)


def total_capital(session: Session) -> float:
    """Total assets = Cash + Inventory balances."""
    return round(
        ledger.account_balance(session, ledger.CASH)
        + ledger.account_balance(session, ledger.INVENTORY),
        2,
    )


def monthly_net_profit(session: Session, since: dt.datetime) -> float:
    revenue = _sum_lines_by_class(session, "Revenue", is_debit=False, since=since)
    expense = _sum_lines_by_class(session, "Expense", is_debit=True, since=since)
    return round(revenue - expense, 2)


def items_in_stock(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(InventoryItem.id)).where(InventoryItem.status.in_(IN_STOCK_STATUSES))
        )
        or 0
    )


def average_inventory_value(session: Session) -> float:
    return round(ledger.account_balance(session, ledger.INVENTORY), 2)


def average_deal_roi(session: Session) -> float:
    """Average ROI across sold items."""
    sold = session.scalars(
        select(InventoryItem).where(InventoryItem.status == "sold")
    ).all()
    rois: list[float] = []
    for item in sold:
        cost = ledger.inventory_cost_of(session, item.id)
        # revenue booked for the item
        rev = session.scalar(
            select(func.coalesce(func.sum(JournalLine.amount), 0.0))
            .join(LedgerAccount, JournalLine.account_id == LedgerAccount.id)
            .where(
                JournalLine.inventory_item_id == item.id,
                LedgerAccount.code == ledger.REVENUE,
                JournalLine.is_debit.is_(False),
            )
        ) or 0.0
        if cost > 0:
            rois.append((float(rev) - cost) / cost * 100.0)
    return round(sum(rois) / len(rois), 2) if rois else 0.0


def turnover_ratio(session: Session) -> float:
    """COGS / average inventory value."""
    cogs = ledger.account_balance(session, ledger.COGS)
    avg_inv = average_inventory_value(session)
    return round(cogs / avg_inv, 2) if avg_inv > 0 else 0.0


def rejected_ratio(session: Session) -> float:
    scanned = int(session.scalar(select(func.coalesce(func.sum(SearchCampaign.scanned_count), 0))) or 0)
    rejected = int(session.scalar(select(func.coalesce(func.sum(SearchCampaign.rejected_count), 0))) or 0)
    return round(rejected / scanned * 100.0, 2) if scanned > 0 else 0.0


def dashboard(session: Session) -> dict:
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    net_profit_month = monthly_net_profit(session, month_start)
    net_profit_all = monthly_net_profit(session, dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc))
    turnover = turnover_ratio(session)
    equity = settings.owner_equity

    campaigns = session.scalars(select(SearchCampaign).order_by(SearchCampaign.id)).all()
    return {
        "total_capital": total_capital(session),
        "net_profit_month": net_profit_month,
        "items_in_stock": items_in_stock(session),
        "avg_deal_roi": average_deal_roi(session),
        "metrics": {
            "turnover_ratio": turnover,
            "avg_realization_days": round(30.0 / turnover, 1) if turnover > 0 else None,
            "return_on_capital_pct": round(net_profit_all / equity * 100.0, 2) if equity > 0 else 0.0,
            "rejected_ratio_pct": rejected_ratio(session),
        },
        "campaigns": [
            {
                "id": c.id,
                "query": c.query,
                "category": c.category,
                "status": c.status,
                "market_price": float(c.market_price) if c.market_price is not None else None,
                "min_discount": float(c.min_discount),
                "scanned_count": c.scanned_count,
                "rejected_count": c.rejected_count,
            }
            for c in campaigns
        ],
    }
