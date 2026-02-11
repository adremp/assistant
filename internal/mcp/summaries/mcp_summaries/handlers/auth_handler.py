"""MCP tools for Telethon authentication."""

from mcp.server.fastmcp import FastMCP

from mcp_summaries.container import get_auth_service
from mcp_summaries.handlers import _err, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def telethon_auth_start(user_id: int, phone: str) -> str:
        """Start Telethon authentication by sending code to phone number. Phone format: +79001234567."""
        try:
            auth = await get_auth_service()
            result = await auth.start_auth(user_id, phone)
            return _ok(result)
        except Exception as e:
            return _err(f"Failed to send code: {e}")

    @mcp.tool()
    async def telethon_auth_submit_code(user_id: int, code: str) -> str:
        """Submit the authentication code received via SMS/Telegram. Code can contain dashes/spaces - they will be stripped."""
        try:
            auth = await get_auth_service()
            result = await auth.submit_code(user_id, code)
            return _ok(result)
        except Exception as e:
            return _err(f"Sign-in failed: {e}")
