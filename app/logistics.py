"""Nova Poshta logistics costing and deal profitability.
==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/logistics.py
==============================================================================

Роль коду в системі:
"Розраховує логістику та маржинальність" (Logistics Costing & Profitability Engine).

Призначення:
Інтеграція з API Нової Пошти, обчислення фактичної/об'ємної ваги, комісій 
накладеного платежу та комісії OLX Доставки для визначення чистого прибутку (Net Profit) та ROI.

Ключові паттерни та рішення розробника:
1. Розрахунок об'ємної ваги (Volumetric Weight):
   Застосовується стандартна формула (L * W * H / 4000). Розрахункова вага
   обирається як `max(фактична_вага, об'ємна_вага)`.
2. Резервний алгоритм (Graceful Fallback):
   При відсутності API-ключа Нової Пошти або мережевих помилках система 
   переходить на табличний тариф (90/135 грн), гарантуючи безперервність роботи.
3. Повна формула комісій та прибутку:
   Враховує комісію за грошовий переказ (2% + 20 грн) та комісію OLX (1% + 15 грн).
4. Дисконтування реалізації (Target Sale Factor):
   Оцінка прибутку розраховується від 95% ринкової ціни ($0.95 * P_market$), 
   що закладає запас міцності для швидкого розпродажу.

Оцінка коду та покращення:
- Плюси: Чітка типізована структура (dataclasses), висока стійкість до збоїв API.
- Мінуси: Використання синхронного `httpx.post` блокує асинхронний потік execution loop
  під час очікування відповіді від Нової Пошти (краще замінити на AsyncClient).

"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

NOVA_POSHTA_URL = "https://api.novaposhta.ua/v2.0/json/"
VOLUMETRIC_DIVISOR = 4000.0
COD_RATE = 0.02          # cash-on-delivery: 2% of declared value ...
COD_FLAT = 20.0          # ... + 20 UAH
OLX_DELIVERY_RATE = 0.01  # OLX Delivery fee: 1% of order ...
OLX_DELIVERY_FLAT = 15.0  # ... + 15 UAH


@dataclass
class LogisticsCost:
    delivery_cost: float
    cod_fee: float
    total_logistic_costs: float
    chargeable_weight: float
    source: str  # "api" or "fallback"


def volumetric_weight(dims: dict | None) -> float:
    if not dims:
        return 0.0
    return (dims["length"] * dims["width"] * dims["height"]) / VOLUMETRIC_DIVISOR


class LogisticsEngine:
    """Computes delivery + cash-on-delivery costs via Nova Poshta's API.

    Falls back to a simple tariff grid when no API key is configured or the API
    call fails, so profitability estimates always resolve.
    """

    def __init__(self, api_key: str, default_recipient_city: str):
        self.api_key = api_key
        self.default_recipient_city = default_recipient_city
        self.url = NOVA_POSHTA_URL

    def calculate_total_costs(
        self,
        sender_city_ref: str,
        price: float,
        weight: float,
        volume_dims: dict | None = None,
    ) -> LogisticsCost:
        chargeable_weight = max(weight, volumetric_weight(volume_dims))
        cod_fee = (price * COD_RATE) + COD_FLAT if price > 0 else 0.0

        if self.api_key and sender_city_ref:
            payload = {
                "apiKey": self.api_key,
                "modelName": "InternetDocument",
                "calledMethod": "getDocumentPrice",
                "methodProperties": {
                    "CitySender": sender_city_ref,
                    "CityRecipient": self.default_recipient_city,
                    "Weight": str(chargeable_weight),
                    "ServiceType": "WarehouseWarehouse",
                    "Cost": str(price),
                    "CargoType": "Parcel",
                },
            }
            try:
                resp = httpx.post(self.url, json=payload, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("data"):
                        delivery_cost = float(data["data"][0]["Cost"])
                        return LogisticsCost(
                            delivery_cost=round(delivery_cost, 2),
                            cod_fee=round(cod_fee, 2),
                            total_logistic_costs=round(delivery_cost + cod_fee, 2),
                            chargeable_weight=round(chargeable_weight, 3),
                            source="api",
                        )
            except Exception:
                pass  # fall through to grid tariff

        fallback_cost = 90.0 if chargeable_weight <= 2 else 135.0
        return LogisticsCost(
            delivery_cost=fallback_cost,
            cod_fee=round(cod_fee, 2),
            total_logistic_costs=round(fallback_cost + cod_fee, 2),
            chargeable_weight=round(chargeable_weight, 3),
            source="fallback",
        )


@dataclass
class Profitability:
    target_price: float
    buy_price: float
    logistics_cost: float
    platform_fee: float
    marketing_cost: float
    net_profit: float
    roi_pct: float


def platform_fee(order_value: float) -> float:
    """OLX Delivery style fee: 1% of order value + 15 UAH."""
    if order_value <= 0:
        return 0.0
    return order_value * OLX_DELIVERY_RATE + OLX_DELIVERY_FLAT


def net_profit(
    market_price: float,
    buy_price: float,
    logistics_cost: float,
    marketing_cost: float = 0.0,
    target_sale_factor: float = 0.95,
) -> Profitability:
    """NP = P_target - P_buy - C_logistics - C_platform_fee - C_marketing."""
    target_price = round(market_price * target_sale_factor, 2)
    fee = round(platform_fee(target_price), 2)
    np_value = target_price - buy_price - logistics_cost - fee - marketing_cost
    invested = buy_price + logistics_cost + fee + marketing_cost
    roi = (np_value / invested * 100.0) if invested > 0 else 0.0
    return Profitability(
        target_price=target_price,
        buy_price=round(buy_price, 2),
        logistics_cost=round(logistics_cost, 2),
        platform_fee=fee,
        marketing_cost=round(marketing_cost, 2),
        net_profit=round(np_value, 2),
        roi_pct=round(roi, 2),
    )
