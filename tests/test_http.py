import asyncio

from telegram_mcp.http import TokenGate

TOKEN = "t" * 40


def call(path, headers=()):
    seen = {}

    async def app(scope, receive, send):
        seen["path"] = scope["path"]
        await send({"type": "http.response.start", "status": 200, "headers": []})

    sent = []

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "path": path, "raw_path": path.encode(), "headers": list(headers)}
    asyncio.run(TokenGate(app, TOKEN)(scope, None, send))
    return sent[0]["status"], seen.get("path")


def test_token_in_path():
    assert call(f"/{TOKEN}/mcp") == (200, "/mcp")


def test_bearer_header():
    assert call("/mcp", [(b"authorization", f"Bearer {TOKEN}".encode())]) == (200, "/mcp")


def test_rejects():
    assert call("/mcp") == (404, None)
    assert call("/wrong/mcp") == (404, None)
    assert call("/mcp", [(b"authorization", b"Bearer wrong")]) == (404, None)
    assert call("/healthz") == (200, None)
