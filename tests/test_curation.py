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


def test_channel_key():
    for raw in ["@Durov", "https://t.me/s/durov/5", "t.me/durov", "durov"]:
        assert curation.channel_key(raw) == "durov"


def test_relative_views():
    posts = [{"id": i, "channel": "a", "views": "100"} for i in range(10)]
    posts[5]["views"] = "500"
    curation.annotate_relative_views(posts)
    assert posts[5]["engagement"] == 5.0
    assert posts[0]["engagement"] == 1.0


def test_archive_and_search(tmp_path, monkeypatch):
    monkeypatch.setattr(curation, "STATE_DIR", tmp_path)
    curation.save_archive("@a", [{"id": 1, "channel": "a", "text": "Про юнит-экономику и CAC"}])
    curation.save_archive("a", [{"id": 2, "channel": "a", "text": "Найм первых сотрудников"}])
    assert len(curation.load_archive("a")) == 2
    assert [p["id"] for p in curation.search_archives("cac юнит")] == [1]
    curation.save_notes("a", "notes")
    assert "notes" in curation.load_notes()
