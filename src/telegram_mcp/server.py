"""MCP server exposing tools to read Telegram channel posts."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from . import account, curation, delivery, public
from .errors import UserError

mcp = MCPServer(
    "telegram",
    instructions=(
        "Read posts from Telegram channels. For 'what's new' questions use get_digest "
        "with a `since` window; cite posts by their t.me links. Channels listed in "
        "TELEGRAM_CHANNELS are the user's default subscriptions. For the curated "
        "'send me only the best' workflow use the `essence` prompt: get_new_posts -> "
        "select by get_interest_profile -> send_to_me -> mark_read."
    ),
)


def _backend(use_account: bool | None):
    """Account mode when configured (or forced), public web preview otherwise."""
    if use_account is None:
        use_account = account.is_configured()
    return account if use_account else public


def parse_since(since: str | None) -> datetime | None:
    """Accept '24h', '3d', '2w', '30m' or an ISO date/datetime."""
    if not since:
        return None
    s = since.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([mhdw])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n),
                 "d": timedelta(days=n), "w": timedelta(weeks=n)}[unit]
        return datetime.now(timezone.utc) - delta
    try:
        dt = datetime.fromisoformat(since.strip())
    except ValueError as e:
        raise UserError(f"Can't parse since='{since}'. Use e.g. '24h', '7d' or '2026-09-01'.") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_post(p: dict, max_chars: int | None = None, show_channel: bool = False) -> str:
    """Compact, token-friendly rendering of a post."""
    head = [p["url"] or f"#{p['id']}"]
    if show_channel:
        head.insert(0, f"[{p['channel']}]")
    if p.get("date"):
        head.append(p["date"][:16].replace("T", " ") + " UTC")
    if p.get("views"):
        head.append(f"{p['views']} views")
    if p.get("media"):
        head.append("+" + ",".join(p["media"]))
    if p.get("engagement"):
        head.append(f"engagement x{p['engagement']}")
    if p.get("forwarded_from"):
        head.append(f"fwd from {p['forwarded_from']}")
    text = p.get("text") or "(no text)"
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip() + f"… [truncated, {len(p['text'])} chars; use get_post]"
    body = text
    extra = [link for link in p.get("links", []) if link not in text]
    if extra:
        body += "\nLinks: " + " ".join(extra[:10])
    return " | ".join(head) + "\n" + body


def render(posts: list[dict], fmt: str, max_chars: int | None, show_channel=False) -> str:
    if fmt == "json":
        return json.dumps(posts, ensure_ascii=False, indent=2)
    if not posts:
        return "No posts found."
    return "\n\n---\n\n".join(format_post(p, max_chars, show_channel) for p in posts)


def _errors(fn):
    """Turn expected failures into readable tool output instead of stack traces."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except UserError as e:
            return f"Error: {e}"

    return wrapper


@mcp.tool()
@_errors
async def get_channel_posts(
    channel: str,
    limit: int = 20,
    since: str | None = None,
    before_id: int | None = None,
    max_chars: int | None = 1500,
    format: str = "text",
    use_account: bool | None = None,
) -> str:
    """Get posts from a Telegram channel, newest first.

    Args:
        channel: Username ("durov", "@durov"), link ("https://t.me/durov");
            in account mode also a numeric id or invite link.
        limit: Max number of posts (1-200).
        since: Only posts newer than this: "24h", "7d", "2w" or ISO date "2026-09-01".
        before_id: Only posts with id lower than this (paging back in history).
        max_chars: Truncate each post's text to this many chars (null = full text).
        format: "text" (compact, default) or "json" (all fields).
        use_account: Force account (true) or public web (false) mode.
    """
    posts = await _backend(use_account).fetch_posts(
        channel, limit=max(1, min(limit, 200)), before_id=before_id, since=parse_since(since)
    )
    return render(posts, format, max_chars)


@mcp.tool()
@_errors
async def search_channel_posts(
    channel: str,
    query: str,
    limit: int = 20,
    max_chars: int | None = 1500,
    format: str = "text",
    use_account: bool | None = None,
) -> str:
    """Full-text search of posts in a Telegram channel (Telegram's own search).

    Args:
        channel: Channel username, link or (account mode) numeric id.
        query: Words to search for.
        limit: Max matches (1-100).
        max_chars: Truncate each post's text (null = full text).
        format: "text" or "json".
        use_account: Force account (true) or public web (false) mode.
    """
    posts = await _backend(use_account).fetch_posts(
        channel, limit=max(1, min(limit, 100)), query=query
    )
    return render(posts, format, max_chars)


@mcp.tool()
@_errors
async def get_post(channel: str, post_id: int | None = None, use_account: bool | None = None) -> str:
    """Get one post in full. Pass a post link as `channel` ("https://t.me/durov/545")
    or a channel plus `post_id`."""
    m = re.search(r"(?:t|telegram)\.me/(?:s/)?(?:c/)?([^/?#]+)/(\d+)", channel)
    if m and post_id is None:
        channel, post_id = m.group(1), int(m.group(2))
    if post_id is None:
        return "Error: provide post_id or a full post link like https://t.me/channel/123."
    post = await _backend(use_account).fetch_post(channel, post_id)
    return format_post(post) if post else f"Post {post_id} not found in {channel} (deleted?)."


@mcp.tool()
@_errors
async def get_digest(
    channels: list[str] | None = None,
    since: str = "24h",
    per_channel_limit: int = 30,
    max_chars: int | None = 600,
    use_account: bool | None = None,
) -> str:
    """Collect recent posts from several channels at once, for "what's new" summaries.

    Args:
        channels: Channels to read. Defaults to TELEGRAM_CHANNELS env (comma-separated).
        since: Time window: "24h", "3d", "1w" or ISO date.
        per_channel_limit: Max posts per channel (1-100).
        max_chars: Truncate each post's text (null = full).
        use_account: Force account (true) or public web (false) mode.
    """
    if not channels:
        channels = [c.strip() for c in os.environ.get("TELEGRAM_CHANNELS", "").split(",") if c.strip()]
    if not channels:
        return ("Error: no channels given and TELEGRAM_CHANNELS is not set. "
                "Pass channels=[...] or ask the user which channels to follow.")
    after = parse_since(since)
    backend = _backend(use_account)
    limit = max(1, min(per_channel_limit, 100))
    results = await asyncio.gather(
        *(backend.fetch_posts(c, limit=limit, since=after) for c in channels),
        return_exceptions=True,
    )
    posts, problems = [], []
    for ch, res in zip(channels, results):
        if isinstance(res, UserError):
            problems.append(f"{ch}: {res}")
        elif isinstance(res, Exception):
            problems.append(f"{ch}: unexpected error {type(res).__name__}: {res}")
        else:
            posts.extend(res)
    posts.sort(key=lambda p: p["date"] or "", reverse=True)
    counts = {}
    for p in posts:
        counts[p["channel"]] = counts.get(p["channel"], 0) + 1
    header = f"{len(posts)} posts since {after:%Y-%m-%d %H:%M} UTC from {len(channels)} channels"
    if counts:
        header += " (" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + ")"
    out = [header]
    if problems:
        out.append("Problems:\n" + "\n".join(f"- {x}" for x in problems))
    out.append(render(posts, "text", max_chars, show_channel=True))
    return "\n\n".join(out)


@mcp.tool()
@_errors
async def get_channel_info(channel: str, use_account: bool | None = None) -> str:
    """Channel title, description, subscriber count and date of the latest post."""
    info = await _backend(use_account).channel_info(channel)
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool()
@_errors
async def list_my_channels(limit: int = 50, channels_only: bool = True) -> str:
    """List channels (or all chats) of the logged-in account with unread counts.
    Account mode only."""
    dialogs = await account.list_dialogs(limit=limit, channels_only=channels_only)
    return "\n".join(
        f"{d['title']} | {'@' + d['username'] if d['username'] else d['id']} | {d['type']} | unread: {d['unread']}"
        for d in dialogs
    ) or "No chats found."


@mcp.prompt()
def digest(channels: str = "", period: str = "24h") -> str:
    """Summarize what's new in Telegram channels."""
    target = f"channels {channels}" if channels else "my default channels"
    return (
        f"Use get_digest for {target} with since='{period}'. Group the news by topic, "
        "merge duplicates across channels, put the most important first, and cite every "
        "item with its t.me link. Answer in the user's language."
    )


def _default_channels(channels: list[str] | None) -> list[str]:
    if channels:
        return channels
    chans = [c.strip() for c in os.environ.get("TELEGRAM_CHANNELS", "").split(",") if c.strip()]
    if not chans:
        raise UserError("No channels given and TELEGRAM_CHANNELS is not set. "
                        "Pass channels=[...] or ask the user which channels to follow.")
    return chans


@mcp.tool()
@_errors
async def get_new_posts(
    channels: list[str] | None = None,
    first_run_since: str = "3d",
    filter_noise: bool = True,
    per_channel_limit: int = 50,
    max_chars: int | None = 2500,
    use_account: bool | None = None,
) -> str:
    """Posts the user has NOT been shown yet (since the last mark_read), across channels.
    Built for the curated feed: obvious noise (ads, giveaways, short or bare-repost posts)
    is dropped, and each post gets `engagement` = views vs the channel's median.
    After delivering the selection, call mark_read with the returned cursor.

    Args:
        channels: Channels to check. Defaults to TELEGRAM_CHANNELS.
        first_run_since: Window for channels never read before ("3d", "1w", ...).
        filter_noise: Drop ads/short posts/bare reposts before returning.
        per_channel_limit: Max new posts per channel (1-200).
        max_chars: Truncate each post (null = full). Keep large: judging needs the text.
        use_account: Force account (true) or public web (false) mode.
    """
    channels = _default_channels(channels)
    seen = curation.load_seen()
    backend = _backend(use_account)
    first_since = parse_since(first_run_since)
    limit = max(1, min(per_channel_limit, 200))

    async def fetch(ch):
        last = seen.get(curation.channel_key(ch))
        posts = await backend.fetch_posts(ch, limit=limit, since=None if last else first_since)
        return [p for p in posts if not last or p["id"] > last]

    results = await asyncio.gather(*(fetch(c) for c in channels), return_exceptions=True)
    posts, problems, cursor, dropped = [], [], {}, {}
    for ch, res in zip(channels, results):
        if isinstance(res, Exception):
            problems.append(f"{ch}: {res}")
            continue
        if res:
            cursor[curation.channel_key(ch)] = max(p["id"] for p in res)
        posts.extend(res)
    curation.annotate_engagement(posts)
    if filter_noise:
        kept = []
        for p in posts:
            reason = curation.noise_reason(p)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
            else:
                kept.append(p)
        posts = kept
    posts.sort(key=lambda p: p["date"] or "", reverse=True)

    lines = [f"{len(posts)} new posts from {len(channels)} channels."]
    if dropped:
        lines.append("Filtered out as noise: " + ", ".join(f"{k}: {v}" for k, v in dropped.items()))
    if problems:
        lines.append("Problems:\n" + "\n".join(f"- {x}" for x in problems))
    lines.append("cursor (pass to mark_read after delivering): " + json.dumps(cursor))
    if posts:
        lines.append(render(posts, "text", max_chars, show_channel=True))
    return "\n\n".join(lines)


@mcp.tool()
@_errors
async def mark_read(cursor: dict[str, int]) -> str:
    """Remember posts as seen so get_new_posts won't return them again.
    Pass the cursor dict from get_new_posts, e.g. {"durov": 548}."""
    seen = curation.load_seen()
    for ch, post_id in cursor.items():
        key = curation.channel_key(ch)
        seen[key] = max(seen.get(key, 0), int(post_id))
    curation.save_seen(seen)
    return f"Marked as read: {', '.join(f'{k} up to #{v}' for k, v in cursor.items()) or 'nothing'}."


@mcp.tool()
@_errors
async def send_to_me(text: str) -> str:
    """Send a message to the user in Telegram (their bot chat, or Saved Messages in
    account mode). Long text is split automatically. Plain text; links stay clickable."""
    return await delivery.send(text)


@mcp.tool()
async def get_interest_profile() -> str:
    """What the user finds valuable vs noise. Use it to select posts for the curated feed."""
    return curation.load_profile()


@mcp.tool()
async def set_interest_profile(profile: str) -> str:
    """Save the user's interest profile (replace the whole text). Update it when the user
    says what they liked or didn't ("больше про юнит-экономику, меньше про AI-хайп")."""
    return f"Saved to {curation.save_profile(profile)}."


@mcp.prompt()
def essence(max_items: str = "5", send: str = "yes") -> str:
    """Отобрать «мякотку» из новых постов экспертов и прислать в Telegram."""
    deliver = (
        "Send the result with send_to_me, then call mark_read with the cursor."
        if send.lower() in ("yes", "да", "true", "1")
        else "Show the result here, then call mark_read with the cursor."
    )
    return f"""You are the user's personal editor for Telegram channels of founders and practitioners.

1. Call get_interest_profile, then get_new_posts.
2. Pick at most {max_items} posts that are genuinely valuable under the profile. Be strict:
   most days only 0-3 posts deserve attention. Engagement is a hint, not a criterion.
   Merge posts that say the same thing.
3. For each pick write in the user's language:
   plain text, like this:
   • Короткий заголовок — автор/канал
   Суть: 2-3 предложения с конкретикой (цифры, шаги, вывод), а не пересказ темы.
   Зачем мне: одна строка, как применить.
   https://t.me/...
4. If nothing is worth it, write one line: "Сегодня ничего стоящего (просмотрено N постов)".
5. End with one line: how many posts were reviewed and from which channels.
6. {deliver} If sending fails, do NOT mark as read."""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
