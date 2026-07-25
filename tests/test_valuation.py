"""
==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: tests/test_valuation.py
==============================================================================

Роль коду в системі:
"Тестує математику та оцінку ринку" (Valuation & Scoring Unit Tests).

Призначення:
Перевірка алгоритму IQR-фільтрації, формули скорингу, детектів ризиків у тексті 
та стійкості оцінки ринкової ціни до шуму й скаму.

Ключові паттерни та рішення розробника:
1. Тест очищення цінових аномалій (IQR Test):
   Підтверджує видалення з масиву крайніх викидів (наприклад, 1 грн або 5000 грн).
2. Тест анкерних точок дисконту (Price Score Ramps):
   Перевіряє, що 25% дисконт дає 100 балів (Sweet Spot), а дисконт >50% дає 0 балів.
3. Тест відсісіювання нерелевантного шуму:
   Підтверджує, що `estimate_market_price` ігнорує чохли та запчастини серед смартфонів.
==============================================================================
"""

import numpy as np

from app.valuation import (
    estimate_market_price,
    iqr_filter,
    price_score,
    reputation_score,
    score_offer,
    text_score,
)


def test_iqr_filter_removes_outliers():
    prices = np.array([100, 102, 98, 101, 99, 100, 5000, 1], dtype=float)
    clean, lower, upper = iqr_filter(prices)
    assert 5000 not in clean
    assert 1 not in clean
    assert lower < 100 < upper


def test_price_score_anchors():
    market = 100.0
    assert price_score(95, market) == 0.0        # 5% discount -> 0
    assert price_score(75, market) == 100.0       # 25% discount -> sweet spot
    assert price_score(45, market) == 0.0         # 55% discount -> fraud, 0
    # 15% discount -> partial ramp
    assert 0 < price_score(85, market) < 100


def test_text_score_green_and_red():
    good, risks_good = text_score("iPhone оригінал", "повний комплект, є чек")
    bad, risks_bad = text_score("iPhone копія", "r-sim, тріщина")
    assert good > bad
    assert "копія" in risks_bad and "r-sim" in risks_bad
    assert risks_good == []


def test_reputation_new_account_penalised():
    assert reputation_score(5) < reputation_score(400)


def test_score_offer_weights():
    s = score_offer(
        buy_price=75,
        market_price=100,
        title="iPhone оригінал",
        description="повний комплект",
        account_age_days=400,
    )
    assert 0 <= s.total <= 100
    assert s.price_score == 100.0
    assert s.discount_pct == 25.0


def test_estimate_market_price_ignores_noise_and_fraud():
    offers = [
        {"title": "iPhone 13 128GB", "description": "оригінал", "price": 20000},
        {"title": "iPhone 13 128GB", "description": "гарний стан", "price": 20500},
        {"title": "iPhone 13 128GB", "description": "повний комплект", "price": 19800},
        {"title": "iPhone 13 128GB", "description": "є чек", "price": 20200},
        {"title": "iPhone 13 128GB", "description": "оригінал", "price": 20100},
        {"title": "Чохол для iPhone 13", "description": "аксесуар", "price": 300},
        {"title": "iPhone 13 на запчастини", "description": "тріщина", "price": 4000},
    ]
    val = estimate_market_price(offers)
    assert 18000 < val.market_price < 22000
    assert val.total_offers == 7
