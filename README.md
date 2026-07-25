# Short Review
Зведення: OLX Arbitrage System (Architecture & Overview)Основне призначення: Пошук, оцінка та автоматизований облік товарного арбітражу на OLX Ukraine.
Головні технічні фічі:
- curl_cffi: Імітація TLS-відбитків Chrome для обходу anti-bot.
- DBSCAN + IQR: Видалення тексту-шуму та цінових аномалій для точного визначення ринкової ціни ($P_{market}$).
- Правило скорингу знижок: Знижки понад 50% автоматично штрафуються до 0 (захист від скаму).
- Double-Entry Ledger: Подвійний запис у Postgres із DB-тригером суворої валідації балансу.

Оцінка архітектури: 10/10 (Промисловий підхід, чіткий розподіл за модулями, висока надійність даних).



OLX Arbitrage System
│
├── 📁 app/                     # Головний пакет додатка
│   ├── acquisition.py          # [Збір даних] Парсер OLX та генератор симуляцій
│   ├── analytics.py            # [Аналітичний центр] Розрахунок KPI та дашборду
│   ├── config.py               # [Менеджер конфігурації] Зчитування та валідація .env
│   ├── db.py                   # [База даних] Пул з'єднань SQLAlchemy та ініціалізація
│   ├── ledger.py               # [Бухгалтерська книга] Подвійний запис та собівартість (COGS)
│   ├── logistics.py            # [Логістика та прибуток] Розрахунок Нової Пошти та комісій
│   ├── main.py                 # [REST API Веб-сервер] Контролери FastAPI та Lifespan
│   ├── models.py               # [ORM Моделі] Структура таблиць PostgreSQL у SQLAlchemy 2.0
│   ├── notifier.py             # [Сповіщення] Telegram-бот для інформування про угоди
│   ├── orchestrator.py         # [Оркестратор] Диригент пошуку, навчання та моніторингу
│   ├── schemas.py              # [Схеми API] Pydantic-моделі входу/виходу даних
│   ├── valuation.py            # [Оцінка та скоринг] TF-IDF, DBSCAN, IQR та оцінка лотів
│   └── 📁 static/              # Веб-інтерфейс (Single Page Application)
│       ├── app.js              # [Логіка фронтенду] AJAX-запити, рендер таблиць та автооновлення
│       ├── index.html          # [Каркас дашборду] HTML5-шаблон панелі оператора
│       └── styles.css          # [Дизайн та тема] CSS-стилі у Dark Mode
│
├── 📁 db/
│   └── schema.sql              # [Схема PostgreSQL] Таблиці, план рахунків та DB-тригер
│
├── 📁 scripts/
│   └── seed.py                 # [Демо-генератор] Наповнення бази початковими даними
│
├── 📁 tests/                   # Набір автотестів (Pytest)
│   ├── conftest.py             # [Фікстури тестів] Створення ізольованої бази `_test`
│   ├── test_ledger.py          # [Тести бухгалтерії] Перевірка проводок та тригерів
│   ├── test_logistics.py       # [Тести логістики] Перевірка об'ємної ваги та тарифікації
│   └── test_valuation.py       # [Тести оцінки] Перевірка IQR-фільтрації та скорингу
│
├── Dockerfile                  # [Контейнеризація] Збірка Python 3.11-slim образу
└── docker-compose.yml          # [Оркестрація інфраструктури] Запуск FastAPI + Postgres 16 + Redis 7



"""
------------------------------------------------------------------------------
1. КОРОВІ МОДУЛІ ДОДАТКА (app/)
------------------------------------------------------------------------------

* app/acquisition.py
  - Назва: [Збір даних]
  - Роль: Парсер оголошень OLX та генератор симуляцій.
  - Функціонал: Отримує нові оголошення з OLX. Використовує `curl_cffi` з
    імітацією Chrome TLS (chrome124) для обходу Cloudflare, відсікає дублікати
    через Redis `SETNX` або генерує синтетичний потік даних у режимі симуляції.

* app/valuation.py
  - Назва: [Математична оцінка]
  - Роль: Очищення ринку та скоринг лотів.
  - Функціонал: Обчислює очищену ринкову ціну (P_market) за допомогою TF-IDF +
    DBSCAN (відсікає чохли й запчастини) та IQR-фільтра (прибирає цінові аномалії).
    Вираховує привабливість лота за формулою S = 0.5*S_price + 0.3*S_text + 0.2*S_reputation.

* app/logistics.py
  - Назва: [Розрахунок маржі]
  - Роль: Логістичний двигун та оцінка прибутку.
  - Функціонал: Вираховує об'ємну вагу (L*W*H/4000), тариф доставки Нової Пошти
    (через API чи fallback-сітку), комісію накладеного платежу та комісію OLX Доставки.
    Розраховує чистий прибуток (Net Profit) та ROI.

* app/ledger.py
  - Назва: [Ведення бухгалтерії]
  - Роль: Подвійна бухгалтерія, облік витрат та COGS.
  - Функціонал: Реалізує повноцінний подвійний запис: кожна дія створює рівні Дебет
    і Кредит. Капіталізує ціну товару, доставку й ремонт у вартість активу та списує
    собівартість (COGS) тільки під час продажу (Matching Principle).

* app/orchestrator.py
  - Назва: [Оркестратор платформи]
  - Роль: Головний мозок конвеєра арбітражу.
  - Функціонал: Керує повним циклом кампанії: створення -> запуск навчання (P_market)
    -> фоновий моніторинг -> потрійний фільтр угод -> відправка вигідних лотів у Telegram.

* app/analytics.py
  - Назва: [Аналітичний центр]
  - Роль: Розрахунок KPI та дашборд-метрики.
  - Функціонал: Агрегує фінансові та операційні дані для дашборду: підраховує капітал,
    місячний прибуток, оборотність товарних запасів (Turnover Ratio), середній термін
    реалізації та окупність капіталу (ROC).

* app/main.py
  - Назва: [REST API сервер]
  - Роль: Веб-контролер FastAPI та управління веб-сервером.
  - Функціонал: Обслуговує HTTP-ендпоінти для фронтенду, пов'язує веб-запити з
    бухгалтерією та оркестратором, керує запуском/зупинкою фонових процесів через `lifespan`.

* app/models.py
  - Назва: [Структура даних ORM]
  - Роль: Моделі бази даних SQLAlchemy 2.0.
  - Функціонал: Описує таблиці PostgreSQL. Використовує UUID для фінансових
    транзакцій та `Numeric(12, 2)` для точного збереження грошових сум без помилок Float.

* app/schemas.py
  - Назва: [Валідатор API]
  - Роль: Pydantic-схеми входу/виходу даних (DTO).
  - Функціонал: Перевіряє сумісність та коректність даних у запитах (`Field(gt=0)`
    для фінансів), захищаючи додаток від від'ємних чи невалідних значень.

* app/notifier.py
  - Назва: [Центр сповіщень]
  - Роль: Telegram-алерт бот.
  - Функціонал: Форматує HTML-повідомлення про знайдені вигідні лоти зі вказуванням
    цін, дисконту, прибутку, ризиків та посилання і відправляє їх у Telegram-чат.

* app/config.py
  - Назва: [Менеджер налаштувань]
  - Роль: Централізований конфіг оточення.
  - Функціонал: Зчитує змінні з `.env` через Pydantic BaseSettings, кешує їх через
    `@lru_cache` (Singleton) та надає зручний доступ до ключів, токенів та режимів роботи.

* app/db.py
  - Назва: [Підключення до БД]
  - Роль: Фабрика сесій SQLAlchemy.
  - Функціонал: Створює з'єднання з PostgreSQL з перевіркою життєздатності сокетів
    (`pool_pre_ping`), надає асинхронні сесії для FastAPI та запускає завантаження SQL-схеми.

------------------------------------------------------------------------------
2. ВЕБ-ІНТЕРФЕЙС / ФРОНТЕНД (app/static/)
------------------------------------------------------------------------------

* app/static/index.html
  - Назва: [Каркас дашборду]
  - Роль: HTML5-шаблон Single Page Application (SPA).
  - Функціонал: Надає двоколонкову структуру для блоків KPI, стратегічних метрик,
    інлайн-форм та таблиць кампаній, угод, складського обліку й бухгалтерії.

* app/static/app.js
  - Назва: [Логіка фронтенду]
  - Роль: Клієнтський контролер інтерактивності (Vanilla JS).
  - Функціонал: Виконує AJAX-запити до REST API, обробляє події через Event Delegation,
    форматує гривні через `Intl.NumberFormat` та опитує дашборд кожні 5 секунд.

* app/static/styles.css
  - Назва: [Дизайн та тема]
  - Роль: UI Theme & Responsive CSS Styles.
  - Функціонал: Забезпечує сучасний Dark Mode у стилі GitHub Dark, розфарбовує
    статуси (.pill), анімує сповіщення (.toast) та адаптує сітку Grid під мобільні екрани.

------------------------------------------------------------------------------
3. БАЗА ДАНИХ, СКРИПТИ ТА ТЕСТИ (db/, scripts/, tests/)
------------------------------------------------------------------------------

* db/schema.sql
  - Назва: [Схема PostgreSQL]
  - Роль: Фундамент бази даних та відкладений тригер.
  - Функціонал: Створює SQL-таблиці та містить тригер `DEFERRABLE INITIALLY DEFERRED`,
    який на рівні PostgreSQL перевіряє рівність `Sum(Debit) == Sum(Credit)` перед кожним COMMIT.

* scripts/seed.py
  - Назва: [Генератор демо-даних]
  - Роль: Скрипт початкового наповнення бази.
  - Функціонал: Заповнює порожню базу реалістичною історією (капітал, покупки,
    маркетинг, продажі), щоб оператор одразу побачив готовий дашборд з аналітикою.

* tests/conftest.py
  - Назва: [Налаштування тестів]
  - Роль: Pytest Bootstrap & Test DB Provisioning.
  - Функціонал: Автоматично створює та підключає окрему ізольовану базу даних з
    суфіксом `_test` для безпечного виконання тестів без псування основної БД.

* tests/test_ledger.py
  - Назва: [Тести бухгалтерії]
  - Роль: Інтеграційна перевірка фінансового обліку.
  - Функціонал: Перевіряє коректність бухгалтерських проводок, капіталізацію витрат,
    списання COGS та блокування незбалансованих транзакцій тригером Postgres.

* tests/test_logistics.py
  - Назва: [Тести логістики]
  - Роль: Модульні тести розрахунку доставки.
  - Функціонал: Перевіряє формулу об'ємної ваги, роботу fallback-тарифікатора Нової
    Пошти без API-ключа та правильність розрахунку чистого прибутку (Net Profit).

* tests/test_valuation.py
  - Назва: [Тести оцінки]
  - Роль: Модульні тести алгоритмів оцінки ринку.
  - Функціонал: Перевіряє видалення цінових викидів через IQR, ваги й штрафи
    формули скорингу та стійкість кластеризації TF-IDF/DBSCAN до аксесуарів і скаму.

------------------------------------------------------------------------------
4. ІНФРАСТРУКТУРА ТА ДЕПЛОЙ (Dockerfile, docker-compose.yml)
------------------------------------------------------------------------------

* Dockerfile & docker-compose.yml
  - Назва: [Контейнеризація та оркестрація]
  - Роль: DevOps Deployment Layer.
  - Функціонал: Збирає легкий Python 3.11-slim контейнер та піднімає всю екосистему
    (FastAPI + PostgreSQL 16 + Redis 7) однією командою з перевіркою готовності через healthcheck.
==============================================================================
"""




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
