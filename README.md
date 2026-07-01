# OLX Arbitrage System

Automated product-arbitrage platform for the OLX Ukraine classifieds, implementing
the architecture from the technical specification: real-time acquisition, market
valuation, logistics costing, double-entry bookkeeping and an analytics dashboard.

## Modules

| Module | Stack | Purpose |
| --- | --- | --- |
| Data Acquisition | `curl_cffi`, Redis | Async collection of new offers, TLS/HTTP2 fingerprint spoofing, proxy rotation, dedup |
| Statistical Engine | NumPy, scikit-learn | DBSCAN clustering + IQR filtering → market price; 0–100 scoring model |
| Logistics & Profitability | httpx, Nova Poshta API | Delivery/COD costing, volumetric weight, net-profit calc |
| Financial Ledger | PostgreSQL | Double-entry bookkeeping with a DB balance-validation trigger |
| Notification & UI | FastAPI, Telegram | Deal alerts and the operator dashboard |

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
# dashboard: http://localhost:8000
```

Seed demo data (optional, from the app container or a local venv):

```bash
docker compose exec app python -m scripts.seed
```

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# start only the datastores
docker compose up -d db redis
cp .env.example .env
python -m scripts.seed          # optional demo data
uvicorn app.main:app --reload   # http://localhost:8000
```

## Operating modes

- **SIMULATION_MODE=true (default):** the acquisition service generates realistic
  synthetic offers (genuine deals, market-priced listings, accessories/noise and
  fraud-like lots). The full pipeline — valuation, scoring, logistics, ledger,
  dashboard — runs with **no proxies or credentials**.
- **SIMULATION_MODE=false (live):** hits OLX's internal offers API via `curl_cffi`
  with Chrome impersonation. Requires residential/mobile proxies (`OLX_PROXIES`)
  and, for hidden phone numbers, OLX OAuth tokens. Configure Nova Poshta and
  Telegram keys in `.env` to enable real logistics costing and alerts.

## Valuation & scoring

1. **Clustering** — offer titles/descriptions are vectorised and grouped with
   DBSCAN; the densest cluster is kept and noise (accessories, broken units) is
   dropped. (A TF-IDF vectoriser stands in for Doc2Vec and is swappable.)
2. **IQR filter** — within the cluster, prices outside `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]`
   are discarded before averaging into `P_market`.
3. **Score** — `S = 0.5·S_price + 0.3·S_text + 0.2·S_reputation`, each in `[0, 100]`.
   Discount sweet spot 20–35%; discounts >50% are penalised to 0 as likely fraud.
   Green/red keyword markers drive `S_text`; account age drives `S_reputation`.

## Double-entry ledger

The PostgreSQL schema (`db/schema.sql`) enforces `debits == credits` per
transaction with a `DEFERRABLE INITIALLY DEFERRED` constraint trigger. The
accounting map:

| Operation | Debit | Credit |
| --- | --- | --- |
| Purchase | Inventory:Products | Cash:BankCard |
| Delivery | Inventory:Products | Cash:BankCard |
| Parts | Inventory:Products | Cash:BankCard |
| Sale (revenue) | Cash:BankCard | Revenue:Sales |
| Sale (COGS) | Expense:ProductCost | Inventory:Products |
| Marketing | Expense:Marketing | Cash:BankCard |

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/dashboard` | KPIs, strategic metrics, campaigns |
| POST | `/api/campaigns` | Create + train a campaign (computes market price) |
| POST | `/api/campaigns/{id}/scan` | Scan for new offers, score, return deals |
| POST | `/api/campaigns/{id}/status?status=` | Pause / activate |
| GET | `/api/campaigns/{id}/offers?deals_only=` | Offers for a campaign |
| GET/POST | `/api/inventory`, `/api/inventory/buy` | Inventory + purchase |
| POST | `/api/inventory/{id}/{delivery,parts,marketing,sell}` | Ledger operations |
| GET | `/api/ledger/trial-balance` | Account balances |
| POST | `/api/ledger/capital` | Inject owner capital |

## Tests

```bash
pytest                 # ledger tests auto-skip if PostgreSQL is unavailable
ruff check .
```

## Disclaimer

Live scraping mode interacts with OLX's non-public endpoints and anti-bot
protections; using it may violate OLX's Terms of Service. Ensure you have the
right to access the data and comply with applicable law before enabling it.
