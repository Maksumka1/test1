"""Telegram notifications for profitable lots."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("arbitrage.notifier")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def notify_deal(self, offer: dict) -> None:
        if not self.enabled:
            log.info("Telegram disabled; deal: %s", offer.get("title"))
            return
        risks = ", ".join(offer.get("risks") or []) or "—"
        text = (
            "🔥 <b>Вигідний лот знайдено</b>\n"
            f"<b>{offer.get('title')}</b>\n"
            f"Ціна: <b>{offer.get('price')} UAH</b>\n"
            f"Ринкова: {offer.get('market_price')} UAH\n"
            f"Дисконт: <b>{offer.get('discount')}%</b>\n"
            f"Скоринг: <b>{offer.get('score')}/100</b>\n"
            f"Прогноз прибутку: <b>{offer.get('net_profit')} UAH</b>\n"
            f"Ризики: {risks}\n"
            f"{offer.get('url')}"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5.0,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram notify failed: %s", exc)
