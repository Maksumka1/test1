"""Data acquisition service.
Two implementations behind a common interface:



# ==============================================================================
# ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/acquisition.py
# ==============================================================================
# Призначення:
# Шлюз збору даних (отримання реальних оголошень OLX або генерація синтетичних даних).
#
# Ключові паттерни та рішення розробника:
# 1. Паттерни "Стратегія" та "Фабрика":
#    `build_parser` динамічно обирає між `AsyncParserPool` та `SimulatedParser`
#    залежно від `settings.simulation_mode`. Обидва класи мають спільний інтерфейс.
# 2. Обхід anti-bot захисту через TLS-імітацію:
#    `curl_cffi` із профілем `chrome124` копіює мережевий відбиток браузера,
#    дозволяючи обходити Cloudflare на внутрішньому API `/api/v1/offers/`.
# 3. Дедуплікація в Redis (`SETNX`):
#    Атомарна команда `redis.set(..., nx=True, ex=86400)` відсікає дублікати
#    оголошень та зберігає статус унікальності на 24 години.
# 4. Реалістичний генератор симуляцій:
#    `SimulatedParser` моделює реальний розподіл ринку:
#    - 15% Аксесуари/Шум (5-15% від базової ціни)
#    - 15% Потенційний скам (30-45% від ціни + слова з RED_WORDS)
#    - 25% Вигідний арбітраж (68-82% від ціни + слова з GREEN_WORDS)
#    - 45% Звичайні ринкові оголошення (92-108% від ціни)
#
# Оцінка коду та покращення:
# - Плюси: Строгі контракти даних (`RawOffer`), "ледачий" імпорт `curl_cffi`,
#   неблокуючий виклику синхронних запитів через `run_in_executor`.
# - Мінуси: Відсутня retry-логіка зі зміною проксі при збоях; парсинг глибоких
#   словників у `_parse_offer` потребує безпечної обробки на випадок зміни API.
# ==============================================================================




TODO / ARCHITECTURE NOTE: Інтеграція GraphQL API та CDN Rating API від OLX

Результати досліджень API OLX:
1. Основний парсинг (acquisition.py):
   - OLX перейшов на GraphQL API (POST https://www.olx.ua/apigateway/graphql).
   - GraphQL віддає повну інформацію за один запит: title, price, description, 
     посилання, ID оголошення та user.created (дата реєстрації продавця).
   - Також повертає user.uuid, який потрібен для виклику сервісу рейтингу.

2. Система репутації та відгуків (valuation.py):
   - Оцінка рейтингу живе на окремому мікросервісі CDN:
     GET https://rating-cdn.css.olx.io/ratings/v1/public/olxua/user/{user_uuid}/eligibleClusters?includeScores=true
   - Повертає: scoreDetails.value (середній бал, напр. 5.0), ratings.totalCount 
     (кількість відгуків) та масив якісних тегів (напр. "Отримане відповідає опису").

3. Що потрібно змінити/дописати під час реалізації:
   - В acquisition.py: переписати HTTP-запит з REST на GraphQL POST-запит (з payload/variables).
   - Додати точковий асинхронний виклик CDN Rating API за `user_uuid` лише для лотів, 
     які пройшли первинний фільтр за ціною (щоб не спамити додатковими запитами).
   - У valuation.py (reputation_score): оновити формулу S_reputation — враховувати 
     не лише вік акаунта (user.created), а й середній бал відгуків (value) та 
     наявність позитивних/негативних тегів із CDN API.
"""




from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone

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
    seller_uuid: str | None = None


class AsyncParserPool:
    """Real OLX parser using curl_cffi + GraphQL API + CDN Rating API + Redis dedup."""

    GRAPHQL_URL = "https://www.olx.ua/apigateway/graphql"

    GRAPHQL_QUERY = """query ListingSearchQuery($searchParameters: [SearchParameter!] = []) {
      clientCompatibleListings(searchParameters: $searchParameters) {
        ... on ListingSuccess {
          data {
            id
            title
            status
            url
            created_time
            last_refresh_time
            description
            business
            location { city { name } }
            photos { link }
            user { id uuid name created }
            params {
              key
              name
              value {
                ... on PriceParam { value currency label }
              }
            }
          }
        }
      }
    }"""

    def __init__(self, proxies: list[str], redis_client):
        self.proxies = proxies or []
        self.redis = redis_client
        self.headers = {
            "accept": "application/json",
            "accept-language": "uk",
            "content-type": "application/json",
            "origin": "https://www.olx.ua",
            "priority": "u=1, i",
            "referer": "https://www.olx.ua/",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="124", "Google Chrome";v="124"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "x-client": "DESKTOP",
        }

    async def fetch_page(self, query: str, page: int = 1) -> dict:
        from curl_cffi import requests

        proxy = random.choice(self.proxies) if self.proxies else None
        
        json_payload = {
            "query": self.GRAPHQL_QUERY,
            "variables": {
                "searchParameters": [
                    {"key": "query", "value": query},
                    {"key": "offset", "value": str((page - 1) * 40)},
                    {"key": "limit", "value": "40"},
                ]
            },
        }

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None,
            lambda: requests.post(
                self.GRAPHQL_URL,
                json=json_payload,
                headers=self.headers,
                proxies={"http": proxy, "https": proxy} if proxy else None,
                impersonate="chrome124",
                timeout=8,
            ),
        )
        response = await future

        if response.status_code == 200:
            return response.json()
        if response.status_code in (401, 403):
            raise PermissionError(
                "Cloudflare/DataDome blocking detected. Rotate proxy or initiate challenge."
            )
        raise ConnectionError(f"HTTP Error {response.status_code}")

    @staticmethod
    def _calculate_account_age_days(created_str: str | None) -> int | None:
        if not created_str:
            return None
        try:
            created_dt = datetime.fromisoformat(created_str)
            now = datetime.now(timezone.utc)
            return max(0, (now - created_dt).days)
        except Exception:
            return None

    def _parse_offer(self, offer: dict) -> RawOffer:
        params = {p.get("key"): p for p in offer.get("params", []) if isinstance(p, dict)}
        price = 0.0
        price_param = params.get("price")
        if price_param:
            price_val = price_param.get("value")
            if isinstance(price_val, dict):
                price = float(price_val.get("value", 0) or 0)

        user_data = offer.get("user") or {}
        created_str = user_data.get("created")
        seller_age = self._calculate_account_age_days(created_str)
        seller_uuid = user_data.get("uuid")

        return RawOffer(
            olx_offer_id=str(offer.get("id")),
            title=offer.get("title", ""),
            description=offer.get("description", ""),
            price=price,
            url=offer.get("url", ""),
            seller_account_age_days=seller_age,
            seller_uuid=seller_uuid,
        )

    async def fetch_new_offers(self, query: str) -> list[RawOffer]:
        raw_data = await self.fetch_page(query, page=1)
        
        listings = (
            raw_data.get("data", {})
            .get("clientCompatibleListings", {})
            .get("data", [])
        )
        
        result: list[RawOffer] = []
        for offer in listings:
            offer_id = str(offer.get("id"))
            is_new = await self._is_new(offer_id)
            if is_new:
                result.append(self._parse_offer(offer))
        return result

    async def training_batch(self, query: str, size: int = 200) -> list[RawOffer]:
        """Збирає ~200 реальних оголошень (сторінки 1..5) для фази навчання ринкової ціни."""
        out: list[RawOffer] = []
        page = 1
        max_pages = (size // 40) + 1
        
        while len(out) < size and page <= max_pages:
            try:
                raw_data = await self.fetch_page(query, page=page)
                listings = (
                    raw_data.get("data", {})
                    .get("clientCompatibleListings", {})
                    .get("data", [])
                )
                if not listings:
                    break
                for offer in listings:
                    out.append(self._parse_offer(offer))
                page += 1
                await asyncio.sleep(0.5)
            except Exception:
                break
                
        return out[:size]

    async def fetch_seller_rating(self, user_uuid: str) -> dict | None:
        """Точковий асинхронний виклик CDN Rating API за user_uuid.
        Викликати лише для лотів, що пройшли первинний фільтр за ціною!
        """
        if not user_uuid:
            return None

        from curl_cffi import requests

        url = f"https://rating-cdn.css.olx.io/ratings/v1/public/olxua/user/{user_uuid}/eligibleClusters?includeScores=true"
        proxy = random.choice(self.proxies) if self.proxies else None

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None,
            lambda: requests.get(
                url,
                headers={"Accept": "application/json", "User-Agent": self.headers["user-agent"]},
                proxies={"http": proxy, "https": proxy} if proxy else None,
                impersonate="chrome124",
                timeout=5,
            ),
        )
        try:
            response = await future
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

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
                price = base * random.uniform(0.05, 0.15)
                title = f"Чохол / аксесуар для {query}"
                desc = "аксесуар, без коробки"
            elif kind < 0.30:
                price = base * random.uniform(0.3, 0.45)
                title = f"{query} терміново"
                desc = f"{random.choice(RED_WORDS)}, {random.choice(RED_WORDS)}"
            elif kind < 0.55:
                price = base * random.uniform(0.68, 0.82)
                title = f"{query} {random.choice(['128GB', '256GB'])}"
                desc = f"{random.choice(GREEN_WORDS)}, {random.choice(GREEN_WORDS)}"
            else:
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
                    seller_uuid="1091cb9b-aa0c-4bad-a91f-72b217655250",
                )
            )
        return offers

    async def fetch_seller_rating(self, user_uuid: str) -> dict | None:
        """Емуляція CDN Rating API для тестів."""
        return {
            "scoreDetails": {"value": 4.9},
            "ratings": {"totalCount": random.randint(10, 150)},
            "badges": ["Отримане відповідає опису", "Швидка відправка"],
        }

    async def training_batch(self, query: str, size: int = 200) -> list[RawOffer]:
        """Емуляція збору 200 оголошень для навчання в симуляційному режимі."""
        base = random.uniform(8000, 30000)
        out: list[RawOffer] = []
        while len(out) < size:
            out.extend(await self.fetch_new_offers(query, base_price=base))
        return out[:size]


def build_parser(settings: Settings, redis_client=None):
    if settings.simulation_mode:
        return SimulatedParser(redis_client)
    return AsyncParserPool(settings.proxy_list, redis_client)