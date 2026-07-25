"""
==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: tests/test_logistics.py
==============================================================================

Роль коду в системі:
"Тестує логістичні розрахунки" (Logistics Unit Tests).

Призначення:
Модульна перевірка обчислення об'ємної ваги, fallback-тарифів Нової Пошти, 
комісій OLX Доставки та розрахунку чистяка (Net Profit).

Ключові паттерни та рішення розробника:
1. Тестування домінування об'ємної ваги:
   Перевіряє, що для великогабаритних товарів розрахункова вага обирається за об'ємом.
2. Тестування резервного алгоритму (Fallback Mode):
   Перевірка коректності роботи логістичного двигуна без API-ключа Нової Пошти.
3. Перевірка формули чистого прибутку:
   Гарантує позитивний Net Profit та ROI для потенційно вигідних угод.
==============================================================================
"""

from app.logistics import (
    LogisticsEngine,
    net_profit,
    platform_fee,
    volumetric_weight,
)


def test_volumetric_weight():
    assert volumetric_weight({"length": 40, "width": 20, "height": 20}) == 4.0
    assert volumetric_weight(None) == 0.0


def test_fallback_tariff_used_without_api_key():
    engine = LogisticsEngine(api_key="", default_recipient_city="ref")
    cost = engine.calculate_total_costs(sender_city_ref="s", price=10000, weight=1.0)
    assert cost.source == "fallback"
    assert cost.delivery_cost == 90.0
    # COD fee = 2% * 10000 + 20
    assert cost.cod_fee == 220.0
    assert cost.total_logistic_costs == 310.0


def test_heavy_parcel_higher_tariff():
    engine = LogisticsEngine(api_key="", default_recipient_city="ref")
    cost = engine.calculate_total_costs(
        sender_city_ref="s", price=5000, weight=1.0,
        volume_dims={"length": 100, "width": 60, "height": 60},
    )
    assert cost.chargeable_weight == 90.0  # volumetric dominates
    assert cost.delivery_cost == 135.0


def test_platform_fee():
    assert platform_fee(10000) == 115.0  # 1% + 15


def test_net_profit_positive_for_good_deal():
    p = net_profit(market_price=24500, buy_price=19500, logistics_cost=310, target_sale_factor=0.95)
    assert p.target_price == 23275.0
    assert p.net_profit > 0
    assert p.roi_pct > 0
