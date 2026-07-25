"""Telegram notifications for profitable lots.

==============================================================================
ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/notifier.py
==============================================================================

Роль коду в системі:
"Відповідає за сповіщення" (Telegram Notification Alert Engine).

Призначення:
Форматування та відправка сповіщень оператору в Telegram про знайдені 
вигідні арбітражні лоти із зазначенням цін, дисконту, скорингу та ризиків.

Ключові паттерни та рішення розробника:
1. Перевірка готовності конфігурації (Dynamic Enabled Check):
   Властивість `enabled` гарантує, що сервіс відпрацює без помилок
   навіть якщо ключі Telegram не задані у `.env`.
2. Грамотна обробка помилок (Fault Tolerance):
   Усі HTTP-запити до Telegram API загорнуті в try-except. Помилки мережі
   чи API логуються як warning і не переривають основну роботу системи.
3. Багате HTML-форматування:
   Використання тегів Telegram HTML для структурованої подачі інформації 
   (виділення прибутку, дисконту, підтягування посилання на лот).
4. Захист від порожніх структур даних:
   Безпечне перетворення списків ризиків через `join(or []) or "—"`.

Оцінка коду та покращення:
- Плюси: Простий, надійний, стійкий до мережевих помилок модуль.
- Мінуси: Синхронний `httpx.post` (блокує потік на 5с при затримках),
  відсутність екранування символів `<`/`>` через `html.escape` для безпечного HTML.

"""
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
