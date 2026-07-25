"""FastAPI application: campaigns, offers, ledger, inventory and dashboard.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/main.py
==============================================================================

Роль коду в системі:
"Обслуговує REST API" (FastAPI Application & API Gateway Controller).

Призначення:
Маршрутизація HTTP-запитів, зв'язування фронтенду з фоновим оркестратором,
керування кампаніями пошуку, облік складських запасів та віддача дашборду.

Ключові паттерни та рішення розробника:
1. Сучасний Lifespan Context Manager:
   Керує ініціалізацією БД та безпечним запуском/зупинкою фонового сканера 
   Оркестратора при старті та завершенні веб-сервера.
2. Сувора ізоляція шарів (DTO / Pydantic schemas):
   Конвертація SQLAlchemy-моделей у вихідні DTO через спеціальні хелпери
   (_campaign_out, _offer_out) запобігає витоку внутрішніх полів бази даних.
3. Автоматична бухгалтерія через ендпоінти:
   Дії з інвентарем (/buy, /sell, /delivery) прямо з'єднані з бухгалтерським 
   модулем `ledger.py`, забезпечуючи 100% покриття транзакцій фінансовими проводками.
4. Централізована обробка 404 помилок:
   Функції `_require_campaign` та `_require_item` гарантують наявність сутностей.

Оцінка коду та покращення:
- Плюси: Лаконічна та чиста структура контролерів, правильне використання lifespan.
- Мінуси: Відсутність пагінації (offset/limit) на списку пропозицій та товарів.

"""
from __future__ import annotations

import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import analytics, ledger
from .config import get_settings
from .db import get_session, init_db
from .models import InventoryItem, Offer, SearchCampaign
from .orchestrator import get_orchestrator
from .schemas import (
    AmountIn,
    BuyIn,
    CampaignCreate,
    CampaignOut,
    CapitalIn,
    InventoryOut,
    OfferOut,
    SellIn,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arbitrage")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    orch = get_orchestrator()
    orch.start_monitor()
    log.info("Startup complete (simulation_mode=%s)", get_settings().simulation_mode)
    try:
        yield
    finally:
        await orch.stop_monitor()


app = FastAPI(title="OLX Arbitrage System", version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------- health
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "simulation_mode": get_settings().simulation_mode}


@app.get("/api/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict:
    return analytics.dashboard(session)


# ------------------------------------------------------------------ campaigns
@app.post("/api/campaigns", response_model=CampaignOut)
def create_campaign(payload: CampaignCreate, session: Session = Depends(get_session)) -> CampaignOut:
    orch = get_orchestrator()
    campaign = orch.create_campaign(
        session,
        query=payload.query,
        category=payload.category,
        min_discount=payload.min_discount,
        weight_kg=payload.weight_kg,
    )
    return _campaign_out(campaign)


@app.get("/api/campaigns", response_model=list[CampaignOut])
def list_campaigns(session: Session = Depends(get_session)) -> list[CampaignOut]:
    rows = session.scalars(select(SearchCampaign).order_by(SearchCampaign.id)).all()
    return [_campaign_out(c) for c in rows]


@app.get("/api/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)) -> CampaignOut:
    return _campaign_out(_require_campaign(session, campaign_id))


@app.post("/api/campaigns/{campaign_id}/scan")
def scan_campaign(campaign_id: int, session: Session = Depends(get_session)) -> dict:
    campaign = _require_campaign(session, campaign_id)
    deals = get_orchestrator().scan_once(session, campaign)
    return {"deals_found": len(deals), "deals": deals}


@app.post("/api/campaigns/{campaign_id}/status", response_model=CampaignOut)
def set_status(campaign_id: int, status: str, session: Session = Depends(get_session)) -> CampaignOut:
    if status not in ("active", "paused"):
        raise HTTPException(400, "status must be 'active' or 'paused'")
    campaign = _require_campaign(session, campaign_id)
    campaign.status = status
    session.commit()
    return _campaign_out(campaign)


@app.get("/api/campaigns/{campaign_id}/offers", response_model=list[OfferOut])
def list_offers(
    campaign_id: int, deals_only: bool = False, session: Session = Depends(get_session)
) -> list[OfferOut]:
    _require_campaign(session, campaign_id)
    stmt = select(Offer).where(Offer.campaign_id == campaign_id)
    if deals_only:
        stmt = stmt.where(Offer.is_deal.is_(True))
    stmt = stmt.order_by(Offer.score.desc().nullslast(), Offer.id.desc())
    rows = session.scalars(stmt).all()
    return [_offer_out(o) for o in rows]


# --------------------------------------------------------------------- ledger
@app.get("/api/ledger/trial-balance")
def trial_balance(session: Session = Depends(get_session)) -> list[dict]:
    return ledger.trial_balance(session)


@app.post("/api/ledger/capital")
def add_capital(payload: CapitalIn, session: Session = Depends(get_session)) -> dict:
    tx = ledger.inject_capital(session, payload.amount)
    return {"transaction_id": str(tx.id)}


# ------------------------------------------------------------------ inventory
@app.get("/api/inventory", response_model=list[InventoryOut])
def list_inventory(session: Session = Depends(get_session)) -> list[InventoryOut]:
    rows = session.scalars(select(InventoryItem).order_by(InventoryItem.id.desc())).all()
    return [_inventory_out(session, i) for i in rows]


@app.post("/api/inventory/buy", response_model=InventoryOut)
def buy_item(payload: BuyIn, session: Session = Depends(get_session)) -> InventoryOut:
    item = InventoryItem(
        title=payload.title,
        olx_offer_id=payload.olx_offer_id,
        purchase_price=payload.purchase_price,
        estimated_market_price=payload.estimated_market_price,
        status="purchased",
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(item)
    session.commit()
    ledger.record_purchase(session, item, payload.purchase_price)
    if payload.delivery_cost > 0:
        ledger.record_delivery(session, item, payload.delivery_cost)
    return _inventory_out(session, item)


@app.post("/api/inventory/{item_id}/delivery", response_model=InventoryOut)
def add_delivery(item_id: int, payload: AmountIn, session: Session = Depends(get_session)) -> InventoryOut:
    item = _require_item(session, item_id)
    ledger.record_delivery(session, item, payload.amount)
    return _inventory_out(session, item)


@app.post("/api/inventory/{item_id}/parts", response_model=InventoryOut)
def add_parts(item_id: int, payload: AmountIn, session: Session = Depends(get_session)) -> InventoryOut:
    item = _require_item(session, item_id)
    ledger.record_parts(session, item, payload.amount)
    return _inventory_out(session, item)


@app.post("/api/inventory/{item_id}/marketing", response_model=InventoryOut)
def add_marketing(item_id: int, payload: AmountIn, session: Session = Depends(get_session)) -> InventoryOut:
    item = _require_item(session, item_id)
    ledger.record_marketing(session, item, payload.amount)
    return _inventory_out(session, item)


@app.post("/api/inventory/{item_id}/sell", response_model=InventoryOut)
def sell_item(item_id: int, payload: SellIn, session: Session = Depends(get_session)) -> InventoryOut:
    item = _require_item(session, item_id)
    if item.status == "sold":
        raise HTTPException(400, "item already sold")
    ledger.record_sale(session, item, payload.sale_price)
    return _inventory_out(session, item)


# --------------------------------------------------------------------- static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# --------------------------------------------------------------------- helpers
def _require_campaign(session: Session, campaign_id: int) -> SearchCampaign:
    campaign = session.get(SearchCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return campaign


def _require_item(session: Session, item_id: int) -> InventoryItem:
    item = session.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(404, "inventory item not found")
    return item


def _campaign_out(c: SearchCampaign) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        query=c.query,
        category=c.category,
        status=c.status,
        market_price=float(c.market_price) if c.market_price is not None else None,
        min_discount=float(c.min_discount),
        weight_kg=float(c.weight_kg),
        scanned_count=c.scanned_count,
        rejected_count=c.rejected_count,
    )


def _offer_out(o: Offer) -> OfferOut:
    return OfferOut(
        id=o.id,
        olx_offer_id=o.olx_offer_id,
        title=o.title,
        price=float(o.price),
        url=o.url,
        score=float(o.score) if o.score is not None else None,
        discount=float(o.discount) if o.discount is not None else None,
        net_profit=float(o.net_profit) if o.net_profit is not None else None,
        is_deal=o.is_deal,
        risks=o.risks,
        seller_account_age_days=o.seller_account_age_days,
    )


def _inventory_out(session: Session, i: InventoryItem) -> InventoryOut:
    return InventoryOut(
        id=i.id,
        title=i.title,
        olx_offer_id=i.olx_offer_id,
        purchase_price=float(i.purchase_price),
        estimated_market_price=float(i.estimated_market_price),
        status=i.status,
        capitalised_cost=ledger.inventory_cost_of(session, i.id),
    )
