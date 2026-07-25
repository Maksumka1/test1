"""Pydantic request/response models.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/schemas.py
==============================================================================

Роль коду в системі:
"Валідує дані API" (Data Validation & DTO Layer / API Schemas).

Призначення:
Опис Pydantic-моделей вхідних запитів та вихідних відповідей REST API,
перевірка типів, бізнес-границь (gt=0) та форматування JSON для Swagger/OpenAPI.

Ключові паттерни та рішення розробника:
1. Захист від від'ємних грошових сум (Field gt=0):
   Всі вхідні фінансові Pydantic-схеми (BuyIn, SellIn, CapitalIn) гарантують, 
   що значення сумиStrictly більше 0, що зберігає цілісність бухгалтерії.
2. Валідація текстових меж (Field min_length/max_length):
   Схема створення кампаній (`CampaignCreate`) захищає від порожніх 
   або занадто довгих пошукових рядків.
3. Сучасна типізація Python 3.10+:
   Використання `Type | None` замість застарілого `Optional[Type]` робить 
   схеми легшими для читання та підтримки.
4. Автоматична генерація OpenAPI (Swagger):
   Pydantic-схеми автоматично будують інтерактивну документацію API.

Оцінка коду та покращення:
- Плюси: Суворий контроль вхідних даних, лаконічний синтаксис, повний захист фінансів.
- Мінуси: Відсутність `from_attributes=True` у DTO-моделях (змушує мапити 
  SQLAlchemy-об'єкти у Pydantic-моделі вручну в контролері).

"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=255)
    category: str | None = None
    min_discount: float = 20.0
    weight_kg: float = 1.0


class CampaignOut(BaseModel):
    id: int
    query: str
    category: str | None
    status: str
    market_price: float | None
    min_discount: float
    weight_kg: float
    scanned_count: int
    rejected_count: int


class OfferOut(BaseModel):
    id: int
    olx_offer_id: str
    title: str
    price: float
    url: str | None
    score: float | None
    discount: float | None
    net_profit: float | None
    is_deal: bool
    risks: str | None
    seller_account_age_days: int | None


class CapitalIn(BaseModel):
    amount: float = Field(..., gt=0)


class BuyIn(BaseModel):
    title: str
    olx_offer_id: str | None = None
    purchase_price: float = Field(..., gt=0)
    estimated_market_price: float = Field(..., gt=0)
    delivery_cost: float = 0.0


class AmountIn(BaseModel):
    amount: float = Field(..., gt=0)


class SellIn(BaseModel):
    sale_price: float = Field(..., gt=0)


class InventoryOut(BaseModel):
    id: int
    title: str
    olx_offer_id: str | None
    purchase_price: float
    estimated_market_price: float
    status: str
    capitalised_cost: float
