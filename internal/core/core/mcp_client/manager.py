"""MCP Client Manager - connects to MCP servers via Streamable HTTP and manages hybrid tool registry."""

import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    Manages connections to MCP servers via Streamable HTTP.

    Uses on-demand connections for each operation to avoid context manager issues.
    """

    def __init__(self):
        self._server_urls: dict[str, str] = {}  # name -> url
        self._cached_tools: dict[str, list] = {}  # name -> tools list
        self._all_tools: dict[str, dict] = {}  # tool_name -> {server_name, schema}

    async def connect(self, name: str, url: str) -> None:
        """
        Connect to an MCP server and fetch available tools.

        Args:
            name: Server name for logging
            url: HTTP endpoint URL (e.g., http://mcp-google:8000/mcp)
        """
        if name in self._server_urls:
            logger.warning(f"Already registered server '{name}'")
            return

        try:
            logger.info(f"Connecting to MCP server '{name}' at {url}")

            # Use the context manager properly
            async with streamablehttp_client(url) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Get available tools
                    tools_result = await session.list_tools()
                    tools = tools_result.tools if hasattr(tools_result, "tools") else []

                    # Store server info
                    self._server_urls[name] = url
                    self._cached_tools[name] = tools

                    # Register tools globally
                    for tool in tools:
                        self._all_tools[tool.name] = {
                            "server_name": name,
                            "schema": tool,
                        }

                    logger.info(f"Connected to '{name}': {len(tools)} tools available")
                    logger.debug(f"Tools from '{name}': {[t.name for t in tools]}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{name}' at {url}: {e}")
            # Don't raise - allow graceful degradation

    async def stop(self) -> None:
        """Clear all cached data."""
        self._server_urls.clear()
        self._cached_tools.clear()
        self._all_tools.clear()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        Call a tool on the appropriate MCP server.

        Creates a new connection for each call (stateless HTTP mode).

        Args:
            name: Tool name
            arguments: Tool arguments (user_id should already be injected)

        Returns:
            Tool result
        """
        tool_info = self._all_tools.get(name)
        if not tool_info:
            raise ValueError(f"Unknown MCP tool: {name}")

        server_name = tool_info["server_name"]
        url = self._server_urls.get(server_name)
        if not url:
            raise RuntimeError(f"MCP server not registered: {server_name}")

        try:
            # Create a new connection for this call
            async with streamablehttp_client(url) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)

                    # Parse result from content
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

            # Convert MCP schema to OpenAI format
            # Remove user_id from parameters (we inject it automatically)
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
        """Get list of all MCP tool names."""
        return list(self._all_tools.keys())


class HybridToolRegistry:
    """
    Combines local tools (respond_to_user) with MCP tools.

    Automatically injects user_id into MCP tool calls.
    """

    def __init__(self, mcp_manager: MCPClientManager | None = None):
        self.mcp_manager = mcp_manager
        self._local_tools: dict[str, Any] = {}
        self._loaded = False

    def _load_local_tools(self) -> None:
        """Load local tools."""
        if self._loaded:
            return

        from core.tools.respond_to_user import RespondToUserTool

        respond_tool = RespondToUserTool()
        self._local_tools[respond_tool.name] = respond_tool
        self._loaded = True

        logger.info(f"Loaded {len(self._local_tools)} local tools")

    def get_all_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools in OpenAI-compatible format.

        Includes both local tools and MCP tools.
        """
        self._load_local_tools()

        tools = []

        # Add local tools
        for tool in self._local_tools.values():
            tools.append(tool.to_openai_tool())

        # Add MCP tools
        if self.mcp_manager:
            mcp_tools = self.mcp_manager.get_tool_schemas()
            tools.extend(mcp_tools)
            if mcp_tools:
                logger.debug(
                    f"Total tools: {len(tools)} (local: {len(self._local_tools)}, MCP: {len(mcp_tools)})"
                )

        return tools

    async def execute_tool(
        self,
        name: str,
        user_id: int,
        arguments: dict[str, Any],
    ) -> Any:
        """
        Execute a tool by name.

        For MCP tools, automatically injects user_id.

        Args:
            name: Tool name
            user_id: Telegram user ID
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        self._load_local_tools()

        # Check local tools first
        if name in self._local_tools:
            logger.info(f"Executing local tool {name} for user {user_id}")
            return await self._local_tools[name].execute(user_id, **arguments)

        # Try MCP tools
        if self.mcp_manager and name in self.mcp_manager.tool_names:
            logger.info(f"Executing MCP tool {name} for user {user_id}")
            # Inject user_id into arguments
            arguments["user_id"] = user_id
            return await self.mcp_manager.call_tool(name, arguments)

        raise ValueError(f"Tool not found: {name}")

    @property
    def tool_names(self) -> list[str]:
        """Get list of all tool names."""
        self._load_local_tools()

        names = list(self._local_tools.keys())
        if self.mcp_manager:
            names.extend(self.mcp_manager.tool_names)
        return names
