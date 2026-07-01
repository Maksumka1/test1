"""Application configuration loaded from environment variables."""
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
