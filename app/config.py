"""Application configuration loaded from environment variables.

==============================================================================
=== ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/config.py ===
==============================================================================

Роль коду в системі:
"Керує налаштуваннями" (Центральний менеджер конфігурації).

Призначення:
Зчитування, типізація, валідація та надання доступу до змінних оточення (.env) для всього додатка.

Ключові паттерни та рішення розробника:

Pydantic BaseSettings:
Автоматично зчитує .env, конвертує типи даних (bool, float, str) та ігнорує невідомі змінні (extra="ignore").

Singleton через @lru_cache:
Функція get_settings() кешує створений об'єкт Settings, уникаючи повторного читання файлу та парсингу при кожному зверненні.

Безпека за замовчуванням:
simulation_mode = True дозволяє запускати проект розробникам без наявності реальних ключів Nova Poshta, Telegram чи проксі.

Зручні обчислювальні властивості:
proxy_list автоматично очищає та парсить рядок olx_proxies у список Python.

Оцінка коду та покращення:

Плюси: Сучасний стандарт FastAPI-додатків, висока швидкість завдяки lru_cache, надійні дефолти.

Мінуси: Відсутня кастомна валідація (наприклад, перевірка наявності ключів Telegram/NovaPoshta, якщо simulation_mode=False).
=====================================================


"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core services
    database_url: str = "postgresql+psycopg://arbitrage:arbitrage@localhost:5432/arbitrage"
    redis_url: str = "redis://localhost:6379/0"

    # Operating mode
    simulation_mode: bool = True

    # Data acquisition
    olx_proxies: str = ""
    olx_poll_min_seconds: float = 2.0
    olx_poll_max_seconds: float = 4.0
    olx_oauth_token: str = ""
    olx_device_id: str = ""

    # Nova Poshta
    nova_poshta_api_key: str = ""
    nova_poshta_recipient_city_ref: str = "8d5a980d-391c-11dd-90d9-001a92567626"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Business defaults
    owner_equity: float = 100000.0
    target_sale_factor: float = 0.95

    @property
    def proxy_list(self) -> list[str]:
        return [p.strip() for p in self.olx_proxies.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
