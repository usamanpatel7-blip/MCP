from telegram_mcp import curation
from telegram_mcp.delivery import split_message

LONG = "x" * 300


def test_parse_views():
    assert curation.parse_views("1.85M") == 1_850_000
    assert curation.parse_views("12K") == 12_000
    assert curation.parse_views("950") == 950
    assert curation.parse_views(None) is None


def test_noise_reason():
    assert curation.noise_reason({"text": "short"}) == "too short"
    assert curation.noise_reason({"text": LONG + " #реклама"}) == "ad"
    assert curation.noise_reason({"text": LONG + " erid: 2Vtzq"}) == "ad"
    assert curation.noise_reason({"text": LONG}) is None


def test_engagement():
    posts = [{"channel": "a", "views": v} for v in ("100", "100", "300")]
    curation.annotate_engagement(posts)
    assert posts[2]["engagement"] == 3.0


def test_seen_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(curation, "STATE_DIR", tmp_path)
    assert curation.load_seen() == {}
    curation.save_seen({"durov": 5})
    assert curation.load_seen() == {"durov": 5}


def test_split_message():
    parts = split_message("a" * 50 + "\n\n" + "b" * 50, limit=60)
    assert parts == ["a" * 50, "b" * 50]
    assert all(len(p) <= 60 for p in split_message("c" * 200, limit=60))
