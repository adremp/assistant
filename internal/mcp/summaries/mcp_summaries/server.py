"""MCP Summaries server - Telegram channel summaries via Telethon."""

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_summaries.handlers.auth_handler import register as register_auth
from mcp_summaries.handlers.channel_handler import register as register_channel
from mcp_summaries.handlers.summary_handler import register as register_summary
from mcp_summaries.handlers.watcher_handler import register as register_watcher

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

security_settings = TransportSecuritySettings(
    allowed_hosts=["mcp-summaries:8000", "localhost:8000", "127.0.0.1:8000", "*"]
)
mcp = FastMCP("summaries", transport_security=security_settings)

register_auth(mcp)
register_channel(mcp)
register_summary(mcp)
register_watcher(mcp)

if __name__ == "__main__":
    import uvicorn

    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
