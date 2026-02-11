"""MCP Google Calendar & Tasks server."""

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_google.handlers.calendar_handler import register as register_calendar
from mcp_google.handlers.tasks_handler import register as register_tasks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

security_settings = TransportSecuritySettings(
    allowed_hosts=["mcp-google:8000", "localhost:8000", "127.0.0.1:8000", "*"]
)
mcp = FastMCP("google-services", transport_security=security_settings)

register_calendar(mcp)
register_tasks(mcp)

if __name__ == "__main__":
    import uvicorn

    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
