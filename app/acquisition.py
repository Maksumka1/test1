"""Data acquisition service.

Two implementations behind a common interface:

* :class:`AsyncParserPool` — the real, low-level scraper from the spec.  It uses
  ``curl_cffi`` to impersonate a modern Chrome TLS/HTTP2 fingerprint, rotates
  through residential/mobile proxies and de-duplicates offers via Redis.  It
  targets OLX's internal mobile API ``/api/v1/offers/``.
* :class:`SimulatedParser` — generates synthetic but realistic offers so the
  whole pipeline (valuation, scoring, ledger, dashboard) runs end-to-end with
  no proxies or credentials.  Selected automatically when SIMULATION_MODE=true.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from .config import Settings
from .valuation import GREEN_WORDS, RED_WORDS


@dataclass
class RawOffer:
    olx_offer_id: str
    title: str
    description: str
    price: float
    url: str
    seller_account_age_days: int | None = None


class AsyncParserPool:
    """Real OLX parser using curl_cffi + proxy rotation + Redis dedup."""

    OFFERS_URL = "https://www.olx.ua/api/v1/offers/"

    def __init__(self, proxies: list[str], redis_client):
        self.proxies = proxies
        self.redis = redis_client
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
            "Version": "2.0",
        }

    async def fetch_page(self, query: str, page: int = 1) -> dict:
        from curl_cffi import requests  # imported lazily so simulation mode has no dep

        proxy = random.choice(self.proxies) if self.proxies else None
        params = {
            "offset": (page - 1) * 40,
            "limit": 40,
            "query": query,
            "sort_by": "created_at:desc",
        }
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None,
            lambda: requests.get(
                self.OFFERS_URL,
                params=params,
                headers=self.headers,
                proxies={"http": proxy, "https": proxy} if proxy else None,
                impersonate="chrome124",
                timeout=8,
            ),
        )
        response = await future
        if response.status_code == 200:
            return response.json()
        if response.status_code == 403:
            raise PermissionError(
                "Cloudflare blocking detected. Rotate proxy or initiate CDP handshake."
            )
        raise ConnectionError(f"HTTP Error {response.status_code}")

    @staticmethod
    def _parse_offer(offer: dict) -> RawOffer:
        params = {p.get("key"): p for p in offer.get("params", [])}
        price = 0.0
        price_param = params.get("price")
        if price_param:
            price = float(price_param.get("value", {}).get("value", 0) or 0)
        return RawOffer(
            olx_offer_id=str(offer.get("id")),
            title=offer.get("title", ""),
            description=offer.get("description", ""),
            price=price,
            url=offer.get("url", ""),
        )

    async def fetch_new_offers(self, query: str) -> list[RawOffer]:
        data = await self.fetch_page(query, page=1)
        result: list[RawOffer] = []
        for offer in data.get("data", []):
            offer_id = str(offer.get("id"))
            is_new = await self._is_new(offer_id)
            if is_new:
                result.append(self._parse_offer(offer))
        return result

    async def _is_new(self, offer_id: str) -> bool:
        if self.redis is None:
            return True
        return bool(await self.redis.set(f"olx:ad:{offer_id}", "1", nx=True, ex=86400))


class SimulatedParser:
    """Generates synthetic offers for demos and tests."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._seq = 0

    async def fetch_new_offers(self, query: str, base_price: float | None = None) -> list[RawOffer]:
        base = base_price or random.uniform(8000, 30000)
        offers: list[RawOffer] = []
        n = random.randint(2, 5)
        for _ in range(n):
            self._seq += 1
            offer_id = f"sim-{query[:6]}-{self._seq}-{random.randint(1000, 9999)}"
            kind = random.random()
            if kind < 0.15:
                # accessory / noise (much cheaper, different item)
                price = base * random.uniform(0.05, 0.15)
                title = f"Чохол / аксесуар для {query}"
                desc = "аксесуар, без коробки"
            elif kind < 0.30:
                # fraud-ish deep discount
                price = base * random.uniform(0.3, 0.45)
                title = f"{query} терміново"
                desc = f"{random.choice(RED_WORDS)}, {random.choice(RED_WORDS)}"
            elif kind < 0.55:
                # a genuine good deal
                price = base * random.uniform(0.68, 0.82)
                title = f"{query} {random.choice(['128GB', '256GB'])}"
                desc = f"{random.choice(GREEN_WORDS)}, {random.choice(GREEN_WORDS)}"
            else:
                # normal market price
                price = base * random.uniform(0.92, 1.08)
                title = f"{query} {random.choice(['128GB', '256GB'])}"
                desc = random.choice(["стан гарний", "оригінал", "повний комплект"])
            offers.append(
                RawOffer(
                    olx_offer_id=offer_id,
                    title=title,
                    description=desc,
                    price=round(price, 2),
                    url=f"https://www.olx.ua/obyavlenie/{offer_id}.html",
                    seller_account_age_days=random.choice([5, 20, 90, 200, 400, 800]),
                )
            )
        return offers

    async def training_batch(self, query: str, size: int = 200) -> list[RawOffer]:
        """Simulate the initial 200-offer market snapshot for model training."""
        base = random.uniform(8000, 30000)
        out: list[RawOffer] = []
        while len(out) < size:
            out.extend(await self.fetch_new_offers(query, base_price=base))
        return out[:size]


def build_parser(settings: Settings, redis_client=None):
    if settings.simulation_mode:
        return SimulatedParser(redis_client)
    return AsyncParserPool(settings.proxy_list, redis_client)
