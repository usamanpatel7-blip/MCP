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
        "Telegram is a primary source for this user. Many founders, product people, "
        "engineers and analysts (especially in the Russian-speaking world) publish only "
        "in Telegram channels, so web search misses them. ALWAYS call search_telegram "
        "alongside web search when the user asks for research, opinions, experience, "
        "cases, best practices, news, market/product/startup/career questions or 'what do "
        "people say about X' — even if Telegram is not mentioned. Search in the language "
        "of the likely sources (try both Russian and English keywords). Cite posts by "
        "their t.me links and say when an insight came from Telegram. "
        "Other workflows: `essence` prompt (curated feed: get_new_posts -> "
        "get_interest_profile -> send_to_me -> mark_read), `study` prompt (deep-dive into "
        "one author: study_channel -> get_post -> save_channel_notes), get_channel_notes "
        "for experts the user already studied."
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
async def search_telegram(
    query: str,
    since: str | None = None,
    limit: int = 15,
    channels: list[str] | None = None,
    max_chars: int | None = 800,
) -> str:
    """Search Telegram for information on any topic. USE THIS BY DEFAULT for research,
    expert opinions, practitioner experience, cases, news and recommendations — together
    with web search — because much expert content lives only in Telegram channels.

    Searches at once: the user's studied experts (local knowledge base), the user's
    channels (TELEGRAM_CHANNELS / subscriptions) and, in account mode, all subscribed
    chats plus Telegram's global search over every public channel.
    Use 2-4 specific keywords, not a sentence; run separate calls for RU and EN.

    Args:
        query: Keywords, e.g. "retention b2b saas" or "найм первого продакта".
        since: Only newer posts: "30d", "1y", ISO date. Default: any time.
        limit: Max results in total (1-50).
        channels: Restrict to these channels instead of the defaults.
        max_chars: Truncate each post (null = full); open interesting ones with get_post.
    """
    limit = max(1, min(limit, 50))
    after = parse_since(since)
    tasks: dict[str, object] = {}
    studied = curation.archived_channels()
    if studied and not channels:
        tasks["knowledge base"] = asyncio.to_thread(curation.search_archives, query)
    targets = channels or [c.strip() for c in os.environ.get("TELEGRAM_CHANNELS", "").split(",") if c.strip()]
    if account.is_configured() and not channels:
        tasks["your subscriptions"] = account.search_my_chats(query, limit=limit, since=after)
        tasks["all public channels"] = account.search_public_posts(query, limit=limit)
    else:
        backend = _backend(None)
        for ch in targets:
            tasks[ch] = backend.fetch_posts(ch, limit=min(limit, 10), query=query, since=after)
    if not tasks:
        return ("Nothing to search: no studied channels, no TELEGRAM_CHANNELS and no account "
                "mode. Ask the user which channels to use, pass channels=[...], or suggest "
                "account mode for searching all of Telegram.")

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    seen_urls, posts, notes = set(), [], []
    for source, res in zip(tasks, results):
        if isinstance(res, Exception):
            notes.append(f"{source}: {res}")
            continue
        found = dupes = 0
        for p in res:
            if after and p.get("date") and datetime.fromisoformat(p["date"]) < after:
                continue
            key = p.get("url") or (p["channel"], p["id"])
            if key not in seen_urls:
                seen_urls.add(key)
                posts.append(p)
                found += 1
            else:
                dupes += 1
        notes.append(f"{source}: {found}" + (f" (+{dupes} already listed)" if dupes else ""))
    posts.sort(key=lambda p: p.get("date") or "", reverse=True)
    posts = posts[:limit]
    head = f"Telegram search '{query}': {len(posts)} results. Sources — " + "; ".join(notes)
    if not posts:
        return head + "\nNo results. Try other keywords, the other language, or a wider `since`."
    return head + "\n\n" + render(posts, "text", max_chars, show_channel=True)


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


@mcp.tool()
@_errors
async def study_channel(
    channel: str,
    since: str = "365d",
    max_posts: int = 600,
    top: int = 25,
    max_chars: int | None = 1500,
    use_account: bool | None = None,
) -> str:
    """Deep-dive into one author's channel: downloads its history (saved locally for
    later search_knowledge), drops noise, and returns channel stats plus the TOP posts
    ranked by how much they outperformed neighbouring posts (resonance with the audience).

    Args:
        channel: The author's channel.
        since: How far back to read ("90d", "365d", "2026-01-01").
        max_posts: Cap on posts to download (1-1200).
        top: How many best posts to return in the result (1-60).
        max_chars: Truncate each returned post (null = full).
        use_account: Force account (true) or public web (false) mode.
    """
    posts = await _backend(use_account).fetch_posts(
        channel, limit=max(1, min(max_posts, 1200)), since=parse_since(since)
    )
    if not posts:
        return f"No posts in {channel} for since={since}."
    path = curation.save_archive(channel, posts)
    curation.annotate_relative_views(posts)
    signal = [p for p in posts if not curation.noise_reason(p)]
    ranked = sorted(signal, key=lambda p: p.get("engagement") or 0, reverse=True)
    best = ranked[: max(1, min(top, 60))]

    dates = sorted(p["date"] for p in posts if p.get("date"))
    days = max(1, (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days) if dates else 1
    avg_len = sum(len(p["text"]) for p in signal) // max(1, len(signal))
    info = [
        f"Channel {channel}: {len(posts)} posts from {dates[0][:10] if dates else '?'} "
        f"to {dates[-1][:10] if dates else '?'} (~{len(posts) / days * 7:.1f}/week).",
        f"Substantive posts: {len(signal)} (avg {avg_len} chars); noise skipped: {len(posts) - len(signal)}.",
        f"Archive saved: {path} (searchable via search_knowledge).",
        f"Hit limit max_posts={max_posts}; raise it or narrow `since` for more."
        if len(posts) >= max_posts else "",
        f"TOP {len(best)} by resonance (engagement = views vs neighbouring posts):",
    ]
    return "\n".join(x for x in info if x) + "\n\n" + render(best, "text", max_chars)


@mcp.tool()
@_errors
async def search_knowledge(
    query: str,
    channels: list[str] | None = None,
    limit: int = 10,
    max_chars: int | None = 1200,
) -> str:
    """Search the locally saved archives of studied channels (instant, offline).
    Use it when answering or researching: "what did my experts say about pricing?".
    All query words must appear in a post; try synonyms and both RU/EN words.

    Args:
        query: Words to find.
        channels: Restrict to these channels (default: all studied).
        limit: Max posts (1-50).
        max_chars: Truncate each post (null = full).
    """
    studied = curation.archived_channels()
    if not studied:
        return "Knowledge base is empty: run study_channel on some channels first."
    hits = curation.search_archives(query, channels)[: max(1, min(limit, 50))]
    if not hits:
        return f"No matches for '{query}' in: {', '.join(studied)}. Try fewer or other words."
    return f"{len(hits)} matches in studied channels.\n\n" + render(hits, "text", max_chars, show_channel=True)


@mcp.tool()
async def save_channel_notes(channel: str, notes: str) -> str:
    """Save your synthesized study notes about a channel/author (Markdown, replaces old).
    These notes are the reusable distilled knowledge for future answers."""
    return f"Saved to {curation.save_notes(channel, notes)}."


@mcp.tool()
async def get_channel_notes(channel: str | None = None) -> str:
    """Study notes for one channel, or for all studied authors if channel is omitted.
    Check these before answering questions in the user's professional area."""
    notes = curation.load_notes(channel)
    if notes:
        return notes
    studied = curation.archived_channels()
    return ("No notes yet. " + (f"Archived but not summarized: {', '.join(studied)}." if studied
            else "Use the `study` prompt to study a channel."))


@mcp.prompt()
def study(channel: str, period: str = "365d", goal: str = "") -> str:
    """Изучить канал автора и вытащить максимум пользы в заметки."""
    focus = f"The user's goal: {goal}. Prioritize what serves it.\n" if goal else ""
    return f"""Study the Telegram channel {channel} as a research analyst. {focus}
1. Call study_channel(channel="{channel}", since="{period}").
2. Read the full text of the most promising top posts with get_post (at least 10), and use
   search_channel_posts for recurring themes you notice.
3. Write notes in the user's language, Markdown, dense and concrete:
   ## Кто автор и чем ценен — опыт, контекст, на чём основаны его выводы
   ## Ключевые идеи — 5-10 тезисов, у каждого ссылка на пост
   ## Фреймворки и методы — как применять, по шагам
   ## Цифры и кейсы — конкретные метрики, результаты, примеры
   ## Неочевидное и спорное — где автор идёт против мейнстрима, и где может ошибаться
   ## Лучшие посты — 10 ссылок с одной строкой «почему читать»
   ## Как использовать — когда в работе вспоминать этого автора
   Only claims backed by posts; cite t.me links. No generic filler.
4. Save with save_channel_notes, then give the user a short summary."""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
