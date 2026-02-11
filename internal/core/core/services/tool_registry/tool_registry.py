"""Tool registry - combines local tools with MCP tools."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from core.repository.mcp_repo import MCPRepository

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for LLM tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def execute(self, user_id: int, **kwargs) -> Any:
        pass

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class RespondToUserTool(BaseTool):
    """Tool for sending responses to the user."""

    @property
    def name(self) -> str:
        return "respond_to_user"

    @property
    def description(self) -> str:
        return (
            "Send a response message to the user. Use this tool to communicate "
            "any information, answers, or results to the user. Always call this "
            "tool at the end of processing to deliver the final response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "The message to send to the user.",
                }
            },
            "required": ["response"],
        }

    async def execute(self, user_id: int, **kwargs) -> str:
        return kwargs.get("response", "")


class ToolRegistry:
    """Combines local tools (respond_to_user) with MCP tools.

    Automatically injects user_id into MCP tool calls.
    """

    def __init__(self, mcp_repo: MCPRepository | None = None):
        self.mcp_repo = mcp_repo
        self._local_tools: dict[str, BaseTool] = {}
        self._loaded = False

    def _load_local_tools(self) -> None:
        if self._loaded:
            return

        respond_tool = RespondToUserTool()
        self._local_tools[respond_tool.name] = respond_tool
        self._loaded = True

        logger.info(f"Loaded {len(self._local_tools)} local tools")

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI-compatible format."""
        self._load_local_tools()

        tools = []

        for tool in self._local_tools.values():
            tools.append(tool.to_openai_tool())

        if self.mcp_repo:
            mcp_tools = self.mcp_repo.get_tool_schemas()
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
        """Execute a tool by name. For MCP tools, automatically injects user_id."""
        self._load_local_tools()

        if name in self._local_tools:
            logger.info(f"Executing local tool {name} for user {user_id}")
            return await self._local_tools[name].execute(user_id, **arguments)

        if self.mcp_repo and name in self.mcp_repo.tool_names:
            logger.info(f"Executing MCP tool {name} for user {user_id}")
            arguments["user_id"] = user_id
            return await self.mcp_repo.call_tool(name, arguments)

        raise ValueError(f"Tool not found: {name}")

    @property
    def tool_names(self) -> list[str]:
        self._load_local_tools()
        names = list(self._local_tools.keys())
        if self.mcp_repo:
            names.extend(self.mcp_repo.tool_names)
        return names
