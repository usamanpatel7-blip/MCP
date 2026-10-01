"""Read Telegram through a user account (MTProto via Telethon).

Works with private channels, groups and chats the account is a member of.
Requires TELEGRAM_API_ID, TELEGRAM_API_HASH and TELEGRAM_SESSION
(a StringSession produced by `telegram-mcp-login`).
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel

from .errors import UserError

_client: TelegramClient | None = None


def is_configured() -> bool:
    return all(
        os.environ.get(k) for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")
    )


async def get_client() -> TelegramClient:
    global _client
    if _client is None:
        if not is_configured():
            raise UserError(
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
        raise UserError("Telegram session is not authorized; run `telegram-mcp-login` again.")
    return _client


def _entity_ref(channel: str):
    channel = channel.strip()
    if channel.lstrip("-").isdigit():
        return int(channel)
    if "/+" in channel or "joinchat" in channel:
        return channel  # invite link; Telethon resolves it if we're a member
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([^/?#]+)", channel)
    return (m.group(1) if m else channel).lstrip("@")


async def _entity(channel: str):
    client = await get_client()
    try:
        return await client.get_entity(_entity_ref(channel))
    except (ValueError, errors.UsernameInvalidError, errors.UsernameNotOccupiedError) as e:
        raise UserError(
            f"Chat '{channel}' not found. Use list_my_channels to see available chats."
        ) from e
    except errors.ChannelPrivateError as e:
        raise UserError(f"'{channel}' is private and this account is not a member.") from e
    except errors.FloodWaitError as e:
        raise UserError(f"Telegram rate limit: retry in {e.seconds} seconds.") from e


def _serialize(msg, entity) -> dict:
    username = getattr(entity, "username", None)
    media = []
    if msg.media is not None:
        media.append(type(msg.media).__name__.replace("MessageMedia", "").lower())
    links = []
    for ent, inner in msg.get_entities_text() if msg.entities else []:
        url = getattr(ent, "url", None) or (inner if inner.startswith("http") else None)
        if url:
            links.append(url)
    fwd = None
    if msg.fwd_from:
        fwd = msg.fwd_from.from_name or (
            str(msg.fwd_from.from_id.channel_id) if getattr(msg.fwd_from.from_id, "channel_id", None) else "unknown"
        )
    if username:
        url = f"https://t.me/{username}/{msg.id}"
    elif isinstance(entity, Channel):
        url = f"https://t.me/c/{entity.id}/{msg.id}"
    else:
        url = None
    return {
        "id": msg.id,
        "channel": username or getattr(entity, "title", None) or str(entity.id),
        "url": url,
        "date": msg.date.isoformat() if msg.date else None,
        "views": msg.views,
        "forwarded_from": fwd,
        "text": msg.message or "",
        "links": links,
        "media": media,
    }


async def list_dialogs(limit: int = 50, channels_only: bool = False) -> list[dict]:
    client = await get_client()
    result = []
    async for d in client.iter_dialogs():
        if channels_only and not (d.is_channel and not d.is_group):
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
    since: datetime | None = None,
) -> list[dict]:
    client = await get_client()
    entity = await _entity(channel)
    out = []
    async for m in client.iter_messages(
        entity, limit=limit, offset_id=before_id or 0, search=query or None
    ):
        if since and m.date < since:
            break
        if m.message or m.media:  # skip service messages
            out.append(_serialize(m, entity))
    return out


async def fetch_post(channel: str, post_id: int) -> dict | None:
    client = await get_client()
    entity = await _entity(channel)
    msg = await client.get_messages(entity, ids=post_id)
    return _serialize(msg, entity) if msg else None


async def channel_info(channel: str) -> dict:
    client = await get_client()
    entity = await _entity(channel)
    info = {
        "title": getattr(entity, "title", None),
        "username": getattr(entity, "username", None),
        "description": None,
        "counters": {},
    }
    if isinstance(entity, Channel):
        full = await client(GetFullChannelRequest(entity))
        info["description"] = full.full_chat.about
        if full.full_chat.participants_count is not None:
            info["counters"]["subscribers"] = str(full.full_chat.participants_count)
    [last] = await client.get_messages(entity, limit=1) or [None]
    info["last_post_date"] = last.date.isoformat() if last else None
    info["last_post_id"] = last.id if last else None
    return info
