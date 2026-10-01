"""Deliver a message to the user in Telegram.

Bot (preferred, isolated): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.
Fallback in account mode: the account's own "Saved Messages".
"""

from __future__ import annotations

import os

import httpx

from . import account
from .errors import UserError

TG_LIMIT = 4000  # Telegram allows 4096; leave room


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    parts, cur = [], ""
    for block in text.split("\n\n"):
        while len(block) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(block[:limit])
            block = block[limit:]
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


async def send(text: str) -> str:
    parts = split_message(text.strip())
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        async with httpx.AsyncClient(timeout=20) as client:
            for part in parts:
                r = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": part, "disable_web_page_preview": True},
                )
                data = r.json()
                if not data.get("ok"):
                    raise UserError(f"Bot API error: {data.get('description')}")
        return f"Sent via bot ({len(parts)} message(s))."
    if account.is_configured():
        client = await account.get_client()
        for part in parts:
            await client.send_message("me", part, link_preview=False)
        return f"Sent to Saved Messages ({len(parts)} message(s))."
    raise UserError(
        "No delivery channel: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
        "(or configure account mode to use Saved Messages)."
    )
