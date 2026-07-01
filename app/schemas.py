"""Pydantic request/response models."""
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
