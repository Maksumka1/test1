"""Seed the database with demo data so the dashboard shows a realistic state.

Usage:
    python -m scripts.seed
"""
from __future__ import annotations

import datetime as dt
import random

from app import ledger
from app.db import SessionLocal, init_db
from app.models import InventoryItem
from app.orchestrator import get_orchestrator


def run() -> None:
    random.seed(42)
    init_db()
    orch = get_orchestrator()

    with SessionLocal() as session:
        # 1) Fund the business
        ledger.inject_capital(session, 145000.0)

        # 2) Create and scan a few campaigns
        for query, discount in [
            ("iPhone 13 Pro Max", 20.0),
            ("Xbox Series X", 25.0),
            ("PlayStation 5 Slim", 22.0),
        ]:
            campaign = orch.create_campaign(session, query=query, min_discount=discount)
            for _ in range(4):
                orch.scan_once(session, campaign)

        # 3) Buy a handful of items, sell some to realise profit/ROI
        deals = [
            ("iPhone 13 Pro Max 256GB", 19500, 24500, 130),
            ("Xbox Series X", 12800, 16200, 150),
            ("PlayStation 5 Slim", 14200, 17800, 160),
            ("iPhone 13 Pro Max 128GB", 18200, 23000, 130),
            ("MacBook Air M1", 24000, 30000, 90),
        ]
        items: list[InventoryItem] = []
        for title, buy, market, delivery in deals:
            item = InventoryItem(
                title=title,
                purchase_price=buy,
                estimated_market_price=market,
                status="purchased",
                created_at=dt.datetime.now(dt.timezone.utc),
            )
            session.add(item)
            session.commit()
            ledger.record_purchase(session, item, buy)
            ledger.record_delivery(session, item, delivery)
            items.append(item)

        # Sell the first three (with a bit of marketing on one)
        ledger.record_marketing(session, items[0], 250.0)
        for item in items[:3]:
            ledger.record_sale(session, item, float(item.estimated_market_price) * 0.96)

    print("Seed complete.")


if __name__ == "__main__":
    run()
