"""MCP server exposing tools to read Telegram channel posts."""

from __future__ import annotations

import json

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from . import account, public

mcp = MCPServer("telegram")


def _backend(use_account: bool | None):
    """Account mode when configured (or forced), public web preview otherwise."""
    if use_account is None:
        use_account = account.is_configured()
    return account if use_account else public


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_channel_posts(
    channel: str,
    limit: int = 20,
    before_id: int | None = None,
    use_account: bool | None = None,
) -> str:
    """Get recent posts from a Telegram channel, newest first.

    Args:
        channel: Channel username ("durov", "@durov"), link ("https://t.me/durov")
            or, in account mode, numeric chat id.
        limit: Number of posts to return (1-200).
        before_id: Only return posts with id lower than this (for paging back).
        use_account: Force account mode (true) or public web mode (false).
            Defaults to account mode if credentials are configured.
    """
    limit = max(1, min(limit, 200))
    posts = await _backend(use_account).fetch_posts(channel, limit=limit, before_id=before_id)
    return _dump(posts)


@mcp.tool()
async def search_channel_posts(
    channel: str,
    query: str,
    limit: int = 20,
    use_account: bool | None = None,
) -> str:
    """Search posts in a Telegram channel by text.

    Args:
        channel: Channel username, link or (account mode) numeric id.
        query: Text to search for.
        limit: Max number of matching posts (1-100).
        use_account: Force account (true) or public web (false) mode.
    """
    limit = max(1, min(limit, 100))
    posts = await _backend(use_account).fetch_posts(channel, limit=limit, query=query)
    return _dump(posts)


@mcp.tool()
async def get_post(channel: str, post_id: int, use_account: bool | None = None) -> str:
    """Get a single post by id (e.g. from https://t.me/<channel>/<post_id>)."""
    post = await _backend(use_account).fetch_post(channel, post_id)
    return _dump(post) if post else f"Post {post_id} not found in {channel}."


@mcp.tool()
async def list_my_channels(limit: int = 50, channels_only: bool = True) -> str:
    """List channels/chats of the logged-in account (account mode only)."""
    return _dump(await account.list_dialogs(limit=limit, channels_only=channels_only))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
