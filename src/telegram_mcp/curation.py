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
    """Stable file-safe key: 'https://t.me/s/Durov/5', '@durov' -> 'durov'."""
    channel = channel.strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([^/?#]+)", channel)
    if m:
        channel = m.group(1)
    return re.sub(r"[^\w-]", "_", channel.lstrip("@").lower())


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


def annotate_relative_views(posts: list[dict], window: int = 15) -> None:
    """For archive analysis: views vs the median of neighbouring posts (±window).
    Comparing with neighbours cancels out channel growth and post age."""
    by_channel: dict[str, list[dict]] = {}
    for p in posts:
        by_channel.setdefault(p["channel"], []).append(p)
    for chan_posts in by_channel.values():
        chan_posts.sort(key=lambda p: p["id"])
        views = [parse_views(p.get("views")) for p in chan_posts]
        for i, p in enumerate(chan_posts):
            if not views[i]:
                continue
            around = [v for v in views[max(0, i - window): i + window + 1] if v]
            if len(around) >= 5:
                p["engagement"] = round(views[i] / median(around), 2)


# --- knowledge base: archives and notes -----------------------------------------

def archive_dir() -> Path:
    return STATE_DIR / "archive"


def notes_dir() -> Path:
    return STATE_DIR / "notes"


def save_archive(channel: str, posts: list[dict]) -> Path:
    """Merge posts into ~/.telegram-mcp/archive/<channel>.jsonl (deduplicated by id)."""
    archive_dir().mkdir(parents=True, exist_ok=True)
    f = archive_dir() / f"{channel_key(channel)}.jsonl"
    existing = {p["id"]: p for p in load_archive(channel)}
    existing.update({p["id"]: p for p in posts})
    lines = [json.dumps(p, ensure_ascii=False) for p in sorted(existing.values(), key=lambda p: p["id"])]
    f.write_text("\n".join(lines) + "\n")
    return f


def load_archive(channel: str) -> list[dict]:
    f = archive_dir() / f"{channel_key(channel)}.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def archived_channels() -> list[str]:
    return sorted(f.stem for f in archive_dir().glob("*.jsonl")) if archive_dir().exists() else []


def search_archives(query: str, channels: list[str] | None = None) -> list[dict]:
    """All words of the query must appear (case-insensitive); ranked by hit count."""
    words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 1]
    hits = []
    for ch in channels or archived_channels():
        for p in load_archive(ch):
            text = (p.get("text") or "").lower()
            if words and all(w in text for w in words):
                hits.append((sum(text.count(w) for w in words), p))
    hits.sort(key=lambda h: (h[0], h[1].get("date") or ""), reverse=True)
    return [p for _, p in hits]


def save_notes(channel: str, notes: str) -> Path:
    notes_dir().mkdir(parents=True, exist_ok=True)
    f = notes_dir() / f"{channel_key(channel)}.md"
    f.write_text(notes)
    return f


def load_notes(channel: str | None = None) -> str | None:
    if channel:
        f = notes_dir() / f"{channel_key(channel)}.md"
        return f.read_text() if f.exists() else None
    if not notes_dir().exists():
        return None
    files = sorted(notes_dir().glob("*.md"))
    return "\n\n".join(f"# === {f.stem} ===\n{f.read_text()}" for f in files) or None
