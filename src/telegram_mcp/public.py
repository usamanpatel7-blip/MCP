"""Read public Telegram channels through the t.me/s/<channel> web preview.

No API keys or login required, but only works for public channels that
have the web preview enabled.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://t.me/s/"
USER_AGENT = "Mozilla/5.0 (compatible; telegram-mcp/0.1)"


def normalize_channel(channel: str) -> str:
    """Accept '@name', 'name', 't.me/name', 'https://t.me/s/name/123'."""
    channel = channel.strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([^/?#]+)", channel)
    if m:
        channel = m.group(1)
    return channel.lstrip("@")


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
        links = []
        if text_el:
            links = [a["href"] for a in text_el.find_all("a", href=True)]

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
                "url": f"https://t.me/{data_post}",
                "date": time_el["datetime"] if time_el and time_el.has_attr("datetime") else None,
                "views": views_el.get_text(strip=True) if views_el else None,
                "text": text,
                "links": links,
                "media": media,
            }
        )
    return posts


async def fetch_posts(
    channel: str,
    limit: int = 20,
    before_id: int | None = None,
    query: str | None = None,
) -> list[dict]:
    """Fetch up to `limit` posts, newest first, paging back through history."""
    channel = normalize_channel(channel)
    collected: dict[int, dict] = {}
    before = before_id
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20
    ) as client:
        while len(collected) < limit:
            params = {}
            if before:
                params["before"] = before
            if query:
                params["q"] = query
            resp = await client.get(BASE_URL + channel, params=params)
            resp.raise_for_status()
            page = parse_posts(resp.text)
            if not page:
                if not collected and before is None:
                    raise ValueError(
                        f"No posts found for '{channel}'. The channel may be private, "
                        "not exist, or have web preview disabled."
                    )
                break
            new = [p for p in page if p["id"] not in collected]
            if not new:
                break
            for p in new:
                collected[p["id"]] = p
            before = min(p["id"] for p in page)
    return sorted(collected.values(), key=lambda p: p["id"], reverse=True)[:limit]


async def fetch_post(channel: str, post_id: int) -> dict | None:
    posts = await fetch_posts(channel, limit=20, before_id=post_id + 1)
    return next((p for p in posts if p["id"] == post_id), None)
