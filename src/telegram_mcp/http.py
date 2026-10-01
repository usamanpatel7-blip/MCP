"""Remote (Streamable HTTP) entry point, for claude.ai web and mobile connectors.

Access is protected by MCP_AUTH_TOKEN. Claude.ai custom connectors take only a URL,
so the token travels in the path:  https://<host>/<MCP_AUTH_TOKEN>/mcp
Clients that can send headers may instead use  Authorization: Bearer <token>  on /mcp.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys

import uvicorn

from .server import mcp

MIN_TOKEN_LEN = 32
log = logging.getLogger("telegram_mcp.http")


class TokenGate:
    """ASGI middleware: only requests carrying the token reach the MCP app."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token
        self.prefix = f"/{token}"

    def _ok(self, a: str) -> bool:
        return hmac.compare_digest(a.encode(), self.token.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/healthz":
            return await _plain(send, 200, b"ok")
        segs = path.split("/", 2)  # ['', '<token>', 'mcp...']
        if len(segs) == 3 and self._ok(segs[1]):
            scope = dict(scope, path="/" + segs[2], raw_path=("/" + segs[2]).encode())
            return await self.app(scope, receive, send)
        auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        if auth.startswith("Bearer ") and self._ok(auth[7:]):
            return await self.app(scope, receive, send)
        return await _plain(send, 404, b"not found")


async def _plain(send, status: int, body: bytes):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})


def build_app(token: str):
    if len(token) < MIN_TOKEN_LEN:
        raise SystemExit(
            f"MCP_AUTH_TOKEN must be at least {MIN_TOKEN_LEN} characters. Generate one with:\n"
            "  python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    # Stateless: every request is independent, so restarts and redeploys don't break chats.
    inner = mcp.streamable_http_app(stateless_http=True, host="0.0.0.0")
    return TokenGate(inner, token)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    app = build_app(os.environ.get("MCP_AUTH_TOKEN", ""))
    port = int(os.environ.get("PORT", "8000"))
    # The token is in the URL path: keep uvicorn's access log off so it never hits logs.
    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
