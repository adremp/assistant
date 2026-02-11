"""MCP tools for watcher CRUD."""

from mcp.server.fastmcp import FastMCP

from mcp_summaries.container import get_watcher_storage
from mcp_summaries.handlers import _err, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def create_watcher(
        user_id: int,
        name: str,
        prompt: str,
        chat_ids: list[str],
        interval_seconds: int = 10800,
    ) -> str:
        """Create a watcher for automatic Telegram chat monitoring. The watcher will periodically check specified chats and filter messages using the given prompt criteria."""
        storage = await get_watcher_storage()
        watcher_id = await storage.create_watcher(
            user_id, name, prompt, chat_ids, interval_seconds
        )
        return _ok({"watcher_id": watcher_id, "message": f"Watcher '{name}' created."})

    @mcp.tool()
    async def list_watchers(user_id: int) -> str:
        """List user's watchers for Telegram chat monitoring."""
        storage = await get_watcher_storage()
        watchers = await storage.get_user_watchers(user_id)
        return _ok({"watchers": watchers, "count": len(watchers)})

    @mcp.tool()
    async def delete_watcher(user_id: int, watcher_id: str) -> str:
        """Delete a watcher by ID."""
        storage = await get_watcher_storage()
        deleted = await storage.delete_watcher(watcher_id)
        if deleted:
            return _ok({"message": "Watcher deleted."})
        return _err("Watcher not found.")
