from telegram_mcp.public import normalize_channel, parse_posts

HTML = """
<div class="tgme_widget_message" data-post="demo/42">
  <div class="tgme_widget_message_text">Hello<br/>world <a href="https://x.y">link</a></div>
  <span class="tgme_widget_message_views">1.2K</span>
  <a class="tgme_widget_message_date"><time datetime="2026-01-01T00:00:00+00:00"></time></a>
</div>
"""


def test_normalize_channel():
    for raw in ["demo", "@demo", "t.me/demo", "https://t.me/s/demo/42", "https://telegram.me/demo"]:
        assert normalize_channel(raw) == "demo"


def test_parse_posts():
    [p] = parse_posts(HTML)
    assert p["id"] == 42
    assert p["url"] == "https://t.me/demo/42"
    assert p["text"] == "Hello\nworld link"
    assert p["links"] == ["https://x.y"]
    assert p["views"] == "1.2K"
    assert p["date"] == "2026-01-01T00:00:00+00:00"


def test_parse_since():
    from datetime import datetime, timedelta, timezone
    from telegram_mcp.server import parse_since
    now = datetime.now(timezone.utc)
    assert abs(parse_since("7d") - (now - timedelta(days=7))).total_seconds() < 5
    assert parse_since("2026-09-01").tzinfo is not None
    assert parse_since(None) is None


def test_format_post_truncates():
    from telegram_mcp.server import format_post
    [p] = parse_posts(HTML)
    out = format_post(p, max_chars=3)
    assert out.startswith("https://t.me/demo/42 | 2026-01-01 00:00 UTC | 1.2K views")
    assert "Hel… [truncated" in out
    assert "Links: https://x.y" in out


def test_invalid_username():
    import pytest
    from telegram_mcp.errors import UserError
    with pytest.raises(UserError):
        normalize_channel("https://t.me/+AbCdEf")
