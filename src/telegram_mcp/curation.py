"""Pieces for the "send me only the good stuff" workflow:
noise filtering, engagement scoring, seen-state and the interest profile."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from statistics import median

STATE_DIR = Path(os.environ.get("TELEGRAM_MCP_HOME", Path.home() / ".telegram-mcp"))

AD_MARKERS = re.compile(
    r"#реклама|#ad\b|#промо|erid[:\s]|реклама\.|на правах рекламы|партн[её]рский пост"
    r"|sponsored|розыгрыш|giveaway|промокод",
    re.IGNORECASE,
)
MIN_TEXT_CHARS = 200

DEFAULT_PROFILE = """\
Мне интересны посты практиков: фаундеров, продакт-менеджеров, экспертов.
Ценно: личный опыт с цифрами и выводами, разбор кейсов и ошибок, фреймворки
и чек-листы, которые можно применить, неочевидные инсайты, сильные мнения
с аргументацией.
Не нужно: анонсы мероприятий и вебинаров, продажа курсов, реклама, мемы,
новости без анализа, поздравления, репосты без комментария.
"""


def parse_views(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    m = re.fullmatch(r"([\d.]+)\s*([KM]?)", str(v).strip(), re.IGNORECASE)
    if not m:
        return None
    mult = {"": 1, "K": 1_000, "M": 1_000_000}[m.group(2).upper()]
    return int(float(m.group(1)) * mult)


def noise_reason(post: dict) -> str | None:
    """Why a post is obviously not worth reading, or None if it may be."""
    text = post.get("text") or ""
    if AD_MARKERS.search(text):
        return "ad"
    if post.get("forwarded_from") and len(text) < MIN_TEXT_CHARS:
        return "bare repost"
    if len(text) < MIN_TEXT_CHARS:
        return "too short"
    return None


def annotate_engagement(posts: list[dict]) -> None:
    """Add `engagement` = views relative to the channel's median in this batch.
    Older posts naturally have more views, so it's a rough signal only."""
    by_channel: dict[str, list[int]] = {}
    for p in posts:
        v = parse_views(p.get("views"))
        if v:
            by_channel.setdefault(p["channel"], []).append(v)
    for p in posts:
        v = parse_views(p.get("views"))
        views = by_channel.get(p["channel"], [])
        if v and len(views) >= 3:
            p["engagement"] = round(v / median(views), 1)


# --- seen state -------------------------------------------------------------

def _state_file() -> Path:
    return STATE_DIR / "seen.json"


def load_seen() -> dict[str, int]:
    try:
        return json.loads(_state_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_seen(seen: dict[str, int]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, indent=2, ensure_ascii=False))
    tmp.replace(_state_file())


def channel_key(channel: str) -> str:
    return channel.strip().lstrip("@").lower()


# --- profile ----------------------------------------------------------------

def load_profile() -> str:
    if os.environ.get("TELEGRAM_INTERESTS"):
        return os.environ["TELEGRAM_INTERESTS"]
    f = STATE_DIR / "profile.md"
    return f.read_text() if f.exists() else DEFAULT_PROFILE


def save_profile(text: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = STATE_DIR / "profile.md"
    f.write_text(text)
    return f
