"""Read Telegram through a user account (MTProto via Telethon).

Works with private channels, groups and chats the account is a member of.
Requires TELEGRAM_API_ID, TELEGRAM_API_HASH and TELEGRAM_SESSION
(a StringSession produced by `telegram-mcp-login`).
"""

from __future__ import annotations

import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from .public import normalize_channel

_client: TelegramClient | None = None


def is_configured() -> bool:
    return all(
        os.environ.get(k) for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")
    )


async def get_client() -> TelegramClient:
    global _client
    if _client is None:
        if not is_configured():
            raise RuntimeError(
                "Account mode is not configured: set TELEGRAM_API_ID, TELEGRAM_API_HASH "
                "and TELEGRAM_SESSION (run `telegram-mcp-login` to get a session)."
            )
        _client = TelegramClient(
            StringSession(os.environ["TELEGRAM_SESSION"]),
            int(os.environ["TELEGRAM_API_ID"]),
            os.environ["TELEGRAM_API_HASH"],
        )
    if not _client.is_connected():
        await _client.connect()
    if not await _client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized; run `telegram-mcp-login` again.")
    return _client


def _entity_ref(channel: str):
    channel = channel.strip()
    if channel.lstrip("-").isdigit():
        return int(channel)
    return normalize_channel(channel)


def _serialize(msg, username: str | None) -> dict:
    media = None
    if msg.media is not None:
        media = type(msg.media).__name__.replace("MessageMedia", "").lower()
    return {
        "id": msg.id,
        "url": f"https://t.me/{username}/{msg.id}" if username else None,
        "date": msg.date.isoformat() if msg.date else None,
        "views": msg.views,
        "forwards": msg.forwards,
        "text": msg.message or "",
        "media": media,
        "reply_to": msg.reply_to_msg_id,
        "grouped_id": msg.grouped_id,
    }


async def list_dialogs(limit: int = 50, channels_only: bool = False) -> list[dict]:
    client = await get_client()
    result = []
    async for d in client.iter_dialogs(limit=None if channels_only else limit):
        if channels_only and not d.is_channel:
            continue
        result.append(
            {
                "id": d.id,
                "title": d.title,
                "username": getattr(d.entity, "username", None),
                "type": "channel" if d.is_channel and not d.is_group else
                        "group" if d.is_group else "user",
                "unread": d.unread_count,
            }
        )
        if len(result) >= limit:
            break
    return result


async def fetch_posts(
    channel: str,
    limit: int = 20,
    before_id: int | None = None,
    query: str | None = None,
) -> list[dict]:
    client = await get_client()
    entity = await client.get_entity(_entity_ref(channel))
    username = getattr(entity, "username", None)
    msgs = await client.get_messages(
        entity, limit=limit, offset_id=before_id or 0, search=query or None
    )
    return [_serialize(m, username) for m in msgs if m is not None]


async def fetch_post(channel: str, post_id: int) -> dict | None:
    client = await get_client()
    entity = await client.get_entity(_entity_ref(channel))
    msg = await client.get_messages(entity, ids=post_id)
    return _serialize(msg, getattr(entity, "username", None)) if msg else None
