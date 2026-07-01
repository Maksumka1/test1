"""Campaign orchestration: training, monitoring, scoring and persistence.

Ties the acquisition, valuation, logistics and ledger modules together and
implements the operator lifecycle from the spec:

    init search -> train model (market price) -> monitor -> filter/notify.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .acquisition import RawOffer, build_parser
from .config import get_settings
from .db import SessionLocal
from .logistics import LogisticsEngine, net_profit
from .models import Offer, SearchCampaign
from .notifier import TelegramNotifier
from .valuation import estimate_market_price, score_offer

log = logging.getLogger("arbitrage.orchestrator")

# Offers scoring at/above this are surfaced as deals.
DEAL_SCORE_THRESHOLD = 70.0


def _run(coro):
    """Run a coroutine to completion from a synchronous context."""
    return asyncio.run(coro)


class Orchestrator:
    def __init__(self):
        self.settings = get_settings()
        self.parser = build_parser(self.settings)
        self.logistics = LogisticsEngine(
            self.settings.nova_poshta_api_key, self.settings.nova_poshta_recipient_city_ref
        )
        self.notifier = TelegramNotifier(
            self.settings.telegram_bot_token, self.settings.telegram_chat_id
        )
        self._monitor_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ training
    def create_campaign(
        self,
        session: Session,
        query: str,
        category: str | None = None,
        min_discount: float = 20.0,
        weight_kg: float = 1.0,
    ) -> SearchCampaign:
        campaign = SearchCampaign(
            query=query,
            category=category,
            status="training",
            min_discount=min_discount,
            weight_kg=weight_kg,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(campaign)
        session.commit()
        self.train_campaign(session, campaign)
        return campaign

    def train_campaign(self, session: Session, campaign: SearchCampaign) -> float:
        """Collect an initial market snapshot and compute P_market."""
        if hasattr(self.parser, "training_batch"):
            raw = _run(self.parser.training_batch(campaign.query, size=200))
        else:
            raw = _run(self.parser.fetch_new_offers(campaign.query))
        valuation = estimate_market_price([r.__dict__ for r in raw])
        campaign.market_price = valuation.market_price
        campaign.scanned_count += len(raw)
        campaign.status = "active"
        session.commit()
        log.info(
            "Trained '%s': market=%.2f from %d offers (%d clean)",
            campaign.query,
            valuation.market_price,
            valuation.total_offers,
            valuation.sample_size,
        )
        return valuation.market_price

    # --------------------------------------------------------------- monitoring
    def scan_once(self, session: Session, campaign: SearchCampaign) -> list[dict]:
        raw = _run(self.parser.fetch_new_offers(campaign.query))
        return self.process_offers(session, campaign, raw)

    def process_offers(
        self, session: Session, campaign: SearchCampaign, raw_offers: list[RawOffer]
    ) -> list[dict]:
        deals: list[dict] = []
        market = float(campaign.market_price or 0.0)
        for raw in raw_offers:
            campaign.scanned_count += 1
            # skip duplicates already stored for this campaign
            exists = session.scalar(
                select(Offer.id).where(
                    Offer.campaign_id == campaign.id, Offer.olx_offer_id == raw.olx_offer_id
                )
            )
            if exists:
                continue

            scored = score_offer(
                buy_price=raw.price,
                market_price=market,
                title=raw.title,
                description=raw.description,
                account_age_days=raw.seller_account_age_days,
            )
            logistics = self.logistics.calculate_total_costs(
                sender_city_ref="", price=market, weight=float(campaign.weight_kg)
            )
            profit = net_profit(
                market_price=market,
                buy_price=raw.price,
                logistics_cost=logistics.total_logistic_costs,
                target_sale_factor=self.settings.target_sale_factor,
            )
            is_deal = (
                scored.total >= DEAL_SCORE_THRESHOLD
                and scored.discount_pct >= float(campaign.min_discount)
                and profit.net_profit > 0
            )
            if not is_deal:
                campaign.rejected_count += 1

            offer = Offer(
                campaign_id=campaign.id,
                olx_offer_id=raw.olx_offer_id,
                title=raw.title,
                description=raw.description,
                price=raw.price,
                url=raw.url,
                seller_account_age_days=raw.seller_account_age_days,
                score=scored.total,
                discount=scored.discount_pct,
                net_profit=profit.net_profit,
                is_deal=is_deal,
                risks=", ".join(scored.risks) if scored.risks else None,
                created_at=dt.datetime.now(dt.timezone.utc),
            )
            session.add(offer)

            if is_deal:
                deal = {
                    "title": raw.title,
                    "price": raw.price,
                    "market_price": market,
                    "discount": scored.discount_pct,
                    "score": scored.total,
                    "net_profit": profit.net_profit,
                    "url": raw.url,
                    "risks": scored.risks,
                }
                deals.append(deal)
                self.notifier.notify_deal(deal)

        session.commit()
        return deals

    # ------------------------------------------------------ background monitor
    async def _monitor_loop(self) -> None:
        import random

        while True:
            try:
                with SessionLocal() as session:
                    campaigns = session.scalars(
                        select(SearchCampaign).where(SearchCampaign.status == "active")
                    ).all()
                    for campaign in campaigns:
                        raw = await self.parser.fetch_new_offers(campaign.query)
                        await asyncio.to_thread(self.process_offers, session, campaign, raw)
            except Exception as exc:  # noqa: BLE001
                log.warning("monitor loop error: %s", exc)
            await asyncio.sleep(
                random.uniform(self.settings.olx_poll_min_seconds, self.settings.olx_poll_max_seconds)
            )

    def start_monitor(self) -> None:
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitor(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
