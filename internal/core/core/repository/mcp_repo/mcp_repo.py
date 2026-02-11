"""MCP repository - connects to MCP servers via Streamable HTTP and manages tool schemas."""

import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPRepository:
    """Manages connections to MCP servers via Streamable HTTP."""

    def __init__(self):
        self._server_urls: dict[str, str] = {}
        self._cached_tools: dict[str, list] = {}
        self._all_tools: dict[str, dict] = {}

    async def connect(self, name: str, url: str) -> None:
        """Connect to an MCP server and fetch available tools."""
        if name in self._server_urls:
            logger.warning(f"Already registered server '{name}'")
            return

        try:
            logger.info(f"Connecting to MCP server '{name}' at {url}")

            async with streamablehttp_client(url) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    tools_result = await session.list_tools()
                    tools = tools_result.tools if hasattr(tools_result, "tools") else []

                    self._server_urls[name] = url
                    self._cached_tools[name] = tools

                    for tool in tools:
                        self._all_tools[tool.name] = {
                            "server_name": name,
                            "schema": tool,
                        }

                    logger.info(f"Connected to '{name}': {len(tools)} tools available")
                    logger.debug(f"Tools from '{name}': {[t.name for t in tools]}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{name}' at {url}: {e}")

    async def stop(self) -> None:
        """Clear all cached data."""
        self._server_urls.clear()
        self._cached_tools.clear()
        self._all_tools.clear()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the appropriate MCP server."""
        tool_info = self._all_tools.get(name)
        if not tool_info:
            raise ValueError(f"Unknown MCP tool: {name}")

        server_name = tool_info["server_name"]
        url = self._server_urls.get(server_name)
        if not url:
            raise RuntimeError(f"MCP server not registered: {server_name}")

        try:
            async with streamablehttp_client(url) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)

                    if hasattr(result, "content") and result.content:
                        content = result.content[0]
                        if hasattr(content, "text"):
                            try:
                                return json.loads(content.text)
                            except json.JSONDecodeError:
                                return content.text
                    return {"result": str(result)}

        except Exception as e:
            logger.error(f"MCP tool call failed: {name} - {e}")
            return {"error": str(e)}

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get all MCP tools in OpenAI-compatible format."""
        tools = []
        for tool_name, tool_info in self._all_tools.items():
            schema = tool_info["schema"]

            input_schema = schema.inputSchema if hasattr(schema, "inputSchema") else {}
            properties = dict(input_schema.get("properties", {}))
            properties.pop("user_id", None)

            required = list(input_schema.get("required", []))
            if "user_id" in required:
                required.remove("user_id")

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": schema.description
                        if hasattr(schema, "description")
                        else "",
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )

        return tools

    @property
    def tool_names(self) -> list[str]:
        return list(self._all_tools.keys())
