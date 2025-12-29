"""Tool registry for loading and executing LLM tools."""

import logging
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from app.tools.base import BaseTool
from app.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for LLM tools with lazy loading."""

    def __init__(self, redis: Redis, token_storage: TokenStorage):
        """
        Initialize tool registry.

        Args:
            redis: Redis client for tools that need storage
            token_storage: Token storage for Google API tools
        """
        self.redis = redis
        self.token_storage = token_storage
        self._tools: dict[str, BaseTool] = {}
        self._loaded = False

    def _load_tools(self) -> None:
        """Load all available tools."""
        if self._loaded:
            return

        # Import tools here to avoid circular imports
        from app.tools.get_calendar_events import GetCalendarEventsTool
        from app.tools.create_calendar_event import CreateCalendarEventTool
        from app.tools.get_tasks import GetTasksTool
        from app.tools.create_task import CreateTaskTool
        from app.tools.complete_task import CompleteTaskTool
        from app.tools.respond_to_user import RespondToUserTool

        tools = [
            GetCalendarEventsTool(self.token_storage),
            CreateCalendarEventTool(self.token_storage),
            GetTasksTool(self.token_storage),
            CreateTaskTool(self.token_storage),
            CompleteTaskTool(self.token_storage),
            RespondToUserTool(),
        ]

        for tool in tools:
            self._tools[tool.name] = tool
            logger.debug(f"Registered tool: {tool.name}")

        self._loaded = True
        logger.info(f"Loaded {len(self._tools)} tools")

    def get_all_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools in OpenAI-compatible format.

        Returns:
            List of tool definitions for OpenAI API
        """
        self._load_tools()
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def get_tool(self, name: str) -> BaseTool | None:
        """
        Get a tool by name.

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        self._load_tools()
        return self._tools.get(name)

    async def execute_tool(
        self,
        name: str,
        user_id: int,
        arguments: dict[str, Any],
    ) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            user_id: Telegram user ID
            arguments: Tool arguments

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found
        """
        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")

        logger.info(f"Executing tool {name} for user {user_id}")
        result = await tool.execute(user_id, **arguments)
        logger.debug(f"Tool {name} completed for user {user_id}")
        return result

    @property
    def tool_names(self) -> list[str]:
        """Get list of all tool names."""
        self._load_tools()
        return list(self._tools.keys())


# Global registry instance (initialized in app startup)
_registry: ToolRegistry | None = None


def init_tool_registry(redis: Redis, token_storage: TokenStorage) -> ToolRegistry:
    """
    Initialize the global tool registry.

    Args:
        redis: Redis client
        token_storage: Token storage instance

    Returns:
        Initialized ToolRegistry
    """
    global _registry
    _registry = ToolRegistry(redis, token_storage)
    return _registry


def get_tool_registry() -> ToolRegistry:
    """
    Get the global tool registry.

    Returns:
        ToolRegistry instance

    Raises:
        RuntimeError: If registry not initialized
    """
    if _registry is None:
        raise RuntimeError("Tool registry not initialized. Call init_tool_registry first.")
    return _registry
