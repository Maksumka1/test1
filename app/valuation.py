"""Market valuation and offer scoring engine.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/valuation.py
==============================================================================

Роль коду в системі:
"Визначає ринкову ціну та оцінює привабливість" (Statistical Engine & Valuation Core).

Призначення:
Семантична кластеризація оголошень (TF-IDF + DBSCAN), статистичне очищення 
цінових аномалій (IQR) для обчислення P_market та багатокритеріальний скоринг (S_total).

Ключові паттерни та рішення розробника:
1. Двоетапна очистка цінових даних:
   - Семантичний фільтр: TF-IDF (1-2 грамові слова) + DBSCAN (косинусна відстань) 
     групують схожі пропозиції та відсікають нерелевантний шум (аксесуари, запчастини).
   - Статистичний фільтр: IQR (Interquartile Range) видаляє цінові викиди 
     поза межами [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
2. Комплексний скоринг лотів S = 0.5*S_price + 0.3*S_text + 0.2*S_reputation:
   - S_price: Максимум (100) при дисконті 20-35%. Дисконт > 50% карається 0 балів (скам).
   - S_text: База 60 балів (+10 за GREEN_WORDS, -25 за RED_WORDS ризики).
   - S_reputation: Градація довіри від віку акаунта продавця (від 10 до 90 балів).
3. Використання Dataclasses:
   Строгі класи `MarketValuation` та `OfferScore` для збереження проміжних результатів.

Оцінка коду та покращення:
- Плюси: Висока точність оцінки ринку, надійний захист від скаму, чиста математика.
- Мінуси: Точний пошук слів-маркерів без урахування відмінків української мови 
  (доцільно додати стемінг або лематизацію для GREEN_WORDS / RED_WORDS).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Quality / risk lexicons (Ukrainian) from the spec.
GREEN_WORDS = [
    "ідеальний",
    "оригінал",
    "куплений в україні",
    "повний комплект",
    "є чек",
    "не розбирався",
    "гарантія",
]
RED_WORDS = [
    "копія",
    "заблокований",
    "r-sim",
    "rsim",
    "mdm",
    "тріщина",
    "екран під заміну",
    "без коробки",
    "терміново",
]

WEIGHT_PRICE = 0.5
WEIGHT_TEXT = 0.3
WEIGHT_REPUTATION = 0.2


@dataclass
class MarketValuation:
    market_price: float
    sample_size: int          # offers in the dominant cluster after IQR
    total_offers: int
    lower_bound: float
    upper_bound: float
    clean_prices: list[float] = field(default_factory=list)


def _vectorize(texts: list[str]) -> np.ndarray:
    """Vectorise offer texts for semantic clustering.

    Word-level TF-IDF over 1-2 grams: shared boilerplate like "iphone 13" gets
    a low IDF weight while distinctive tokens ("128gb", "чохол", "запчастини")
    dominate, so accessories and broken units separate from genuine listings.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(
        lowercase=True,
        analyzer="word",
        ngram_range=(1, 2),
        min_df=1,
    )
    matrix = vec.fit_transform(texts)
    return matrix.toarray()


def cluster_offers(texts: list[str], eps: float = 0.7, min_samples: int = 3) -> np.ndarray:
    """Return a DBSCAN cluster label per offer (-1 == noise)."""
    from sklearn.cluster import DBSCAN

    if len(texts) < min_samples:
        # Not enough data to cluster: treat everything as one group.
        return np.zeros(len(texts), dtype=int)

    vectors = _vectorize(texts)
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine").fit_predict(vectors)
    if np.all(labels == -1):
        # Density clustering found only noise; fall back to a single group so
        # the IQR filter can still produce a price.
        return np.zeros(len(texts), dtype=int)
    return labels


def iqr_filter(prices: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return (clean_prices, lower_bound, upper_bound) using 1.5*IQR fences."""
    if prices.size == 0:
        return prices, 0.0, 0.0
    q1 = float(np.percentile(prices, 25))
    q3 = float(np.percentile(prices, 75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    mask = (prices >= lower) & (prices <= upper)
    return prices[mask], lower, upper


def estimate_market_price(offers: list[dict]) -> MarketValuation:
    """Estimate the market price from a batch of offers.

    Each offer dict needs ``title`` (and optionally ``description``) and
    ``price``.  Offers are clustered semantically; the densest cluster is kept,
    IQR-filtered and averaged.
    """
    total = len(offers)
    if total == 0:
        return MarketValuation(0.0, 0, 0, 0.0, 0.0, [])

    texts = [f"{o.get('title', '')} {o.get('description', '')}".strip() for o in offers]
    prices = np.array([float(o["price"]) for o in offers], dtype=float)
    labels = cluster_offers(texts)

    # Pick the densest non-noise cluster (largest membership).
    valid = labels[labels != -1]
    if valid.size == 0:
        target_label = 0
        cluster_mask = np.ones(total, dtype=bool)
    else:
        unique, counts = np.unique(valid, return_counts=True)
        target_label = int(unique[int(np.argmax(counts))])
        cluster_mask = labels == target_label

    cluster_prices = prices[cluster_mask]
    clean, lower, upper = iqr_filter(cluster_prices)
    if clean.size == 0:
        clean = cluster_prices
    market_price = float(np.mean(clean)) if clean.size else 0.0

    return MarketValuation(
        market_price=round(market_price, 2),
        sample_size=int(clean.size),
        total_offers=total,
        lower_bound=round(float(lower), 2),
        upper_bound=round(float(upper), 2),
        clean_prices=[round(float(p), 2) for p in clean.tolist()],
    )


# ---------------------------------------------------------------------------
# Scoring model
# ---------------------------------------------------------------------------
def price_score(buy_price: float, market_price: float) -> float:
    """S_price in [0, 100] from the discount vs market.

    - discount < 10%      -> 0
    - discount 20%-35%     -> 100 (sweet spot)
    - discount > 50%       -> 0   (likely fraud)
    Linear ramps connect these anchors.
    """
    if market_price <= 0:
        return 0.0
    discount = 1.0 - (buy_price / market_price)
    d = discount * 100.0  # percent

    if d < 10.0:
        return 0.0
    if d < 20.0:
        return (d - 10.0) / 10.0 * 100.0          # 10%..20% -> 0..100
    if d <= 35.0:
        return 100.0                               # sweet spot
    if d <= 50.0:
        return (50.0 - d) / 15.0 * 100.0           # 35%..50% -> 100..0
    return 0.0                                      # >50% penalised to zero


def text_score(title: str, description: str = "") -> tuple[float, list[str]]:
    """S_text in [0, 100] from green/red keyword markers, plus detected risks."""
    corpus = f"{title} {description}".lower()
    green_hits = sum(1 for w in GREEN_WORDS if w in corpus)
    red_hits_words = [w for w in RED_WORDS if w in corpus]
    red_hits = len(red_hits_words)

    # Base 60, +10 per green marker, -25 per red marker, clamped to [0, 100].
    score = 60.0 + green_hits * 10.0 - red_hits * 25.0
    score = max(0.0, min(100.0, score))
    return score, red_hits_words


def reputation_score(account_age_days: int | None, successful_deals: int = 0) -> float:
    """S_reputation in [0, 100] from seller account age and history."""
    if account_age_days is None:
        return 40.0
    if account_age_days < 30:
        age_component = 10.0                        # registered this month -> minimal
    elif account_age_days < 180:
        age_component = 50.0
    elif account_age_days < 365:
        age_component = 75.0
    else:
        age_component = 90.0
    deal_component = min(10.0, successful_deals * 2.0)
    return min(100.0, age_component + deal_component)


@dataclass
class OfferScore:
    total: float
    price_score: float
    text_score: float
    reputation_score: float
    discount_pct: float
    risks: list[str] = field(default_factory=list)


def score_offer(
    buy_price: float,
    market_price: float,
    title: str,
    description: str = "",
    account_age_days: int | None = None,
    successful_deals: int = 0,
) -> OfferScore:
    sp = price_score(buy_price, market_price)
    st, risks = text_score(title, description)
    sr = reputation_score(account_age_days, successful_deals)
    total = WEIGHT_PRICE * sp + WEIGHT_TEXT * st + WEIGHT_REPUTATION * sr
    discount = (1.0 - buy_price / market_price) * 100.0 if market_price > 0 else 0.0
    return OfferScore(
        total=round(total, 2),
        price_score=round(sp, 2),
        text_score=round(st, 2),
        reputation_score=round(sr, 2),
        discount_pct=round(discount, 2),
        risks=risks,
    )
