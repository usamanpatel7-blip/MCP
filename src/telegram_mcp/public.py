"""Read public Telegram channels through the t.me/s/<channel> web preview.

No API keys or login required, but only works for public channels that
have the web preview enabled.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .errors import UserError

BASE_URL = "https://t.me/s/"
USER_AGENT = "Mozilla/5.0 (compatible; telegram-mcp/0.2)"
CACHE_TTL = 120  # seconds; avoids refetching the same page within one conversation
MAX_PAGES = 60  # hard stop when paging back through history (~20 posts per page)

_cache: dict[str, tuple[float, str]] = {}


def normalize_channel(channel: str) -> str:
    """Accept '@name', 'name', 't.me/name', 'https://t.me/s/name/123'."""
    channel = channel.strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([^/?#]+)", channel)
    if m:
        channel = m.group(1)
    channel = channel.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", channel):
        raise UserError(
            f"'{channel}' is not a valid public channel username. "
            "Private channels and invite links (t.me/+...) need account mode."
        )
    return channel


async def _get(client: httpx.AsyncClient, channel: str, params: dict) -> str:
    key = f"{channel}?{sorted(params.items())}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        resp = await client.get(BASE_URL + channel, params=params)
    except httpx.HTTPError as e:
        raise UserError(f"Could not reach t.me: {e}") from e
    if resp.status_code == 429:
        raise UserError("Telegram is rate-limiting requests; try again in a minute.")
    if resp.status_code >= 400:
        raise UserError(f"t.me returned HTTP {resp.status_code} for '{channel}'.")
    # Unknown or private channels redirect to the plain t.me/<name> page.
    if "/s/" not in str(resp.url):
        raise UserError(
            f"Channel '{channel}' was not found, is private, or has web preview disabled. "
            "Use account mode for private channels."
        )
    _cache[key] = (time.monotonic(), resp.text)
    return resp.text


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20
    )


def parse_posts(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        data_post = msg["data-post"]
        post_id = int(data_post.rsplit("/", 1)[1])

        text_el = msg.select_one(".tgme_widget_message_text")
        if text_el:
            for br in text_el.find_all("br"):
                br.replace_with("\n")
            text = text_el.get_text()
        else:
            text = ""

        time_el = msg.select_one(".tgme_widget_message_date time")
        views_el = msg.select_one(".tgme_widget_message_views")
        fwd_el = msg.select_one(".tgme_widget_message_forwarded_from_name")
        links = []
        if text_el:
            links = [a["href"] for a in text_el.find_all("a", href=True)
                     if a["href"].startswith("http")]

        media = []
        if msg.select_one(".tgme_widget_message_photo_wrap"):
            media.append("photo")
        if msg.select_one(".tgme_widget_message_video_player"):
            media.append("video")
        if msg.select_one(".tgme_widget_message_document"):
            media.append("document")
        if msg.select_one(".tgme_widget_message_poll"):
            media.append("poll")

        posts.append(
            {
                "id": post_id,
                "channel": data_post.rsplit("/", 1)[0],
                "url": f"https://t.me/{data_post}",
                "date": time_el["datetime"] if time_el and time_el.has_attr("datetime") else None,
                "views": views_el.get_text(strip=True) if views_el else None,
                "forwarded_from": fwd_el.get_text(strip=True) if fwd_el else None,
                "text": text,
                "links": links,
                "media": media,
            }
        )
    return posts


def parse_channel_info(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def txt(sel):
        el = soup.select_one(sel)
        return el.get_text("\n", strip=True) if el else None

    counters = {}
    for c in soup.select(".tgme_channel_info_counter"):
        v, t = c.select_one(".counter_value"), c.select_one(".counter_type")
        if v and t:
            counters[t.get_text(strip=True)] = v.get_text(strip=True)
    return {
        "title": txt(".tgme_channel_info_header_title"),
        "username": txt(".tgme_channel_info_header_username"),
        "description": txt(".tgme_channel_info_description"),
        "counters": counters,
    }


async def fetch_posts(
    channel: str,
    limit: int = 20,
    before_id: int | None = None,
    query: str | None = None,
    since: datetime | None = None,
) -> list[dict]:
    """Fetch up to `limit` posts newest first, optionally only those after `since`."""
    channel = normalize_channel(channel)
    collected: dict[int, dict] = {}
    before = before_id
    async with _client() as client:
        for _ in range(MAX_PAGES):
            params = {}
            if before:
                params["before"] = before
            if query:
                params["q"] = query
            page = parse_posts(await _get(client, channel, params))
            new = [p for p in page if p["id"] not in collected]
            if not new:
                break
            reached_since = False
            for p in new:
                if since and p["date"] and datetime.fromisoformat(p["date"]) < since:
                    reached_since = True
                    continue
                collected[p["id"]] = p
            if reached_since or len(collected) >= limit:
                break
            before = min(p["id"] for p in page)
    return sorted(collected.values(), key=lambda p: p["id"], reverse=True)[:limit]


async def fetch_post(channel: str, post_id: int) -> dict | None:
    posts = await fetch_posts(channel, limit=20, before_id=post_id + 1)
    return next((p for p in posts if p["id"] == post_id), None)


async def channel_info(channel: str) -> dict:
    channel = normalize_channel(channel)
    async with _client() as client:
        html = await _get(client, channel, {})
    info = parse_channel_info(html)
    posts = parse_posts(html)
    info["last_post_date"] = posts[-1]["date"] if posts else None
    info["last_post_id"] = posts[-1]["id"] if posts else None
    return info
