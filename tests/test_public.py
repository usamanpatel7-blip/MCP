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
