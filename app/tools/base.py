"""Base class for LLM tools."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """
    Abstract base class for LLM tools.
    
    Each tool should be defined in its own file with:
    - name: Unique identifier for the tool
    - description: Description for LLM to understand when to use it
    - parameters: JSON Schema for tool parameters
    - execute: Async method to execute the tool
    """

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, user_id: int, **kwargs: Any) -> Any:
        """
        Execute the tool with given parameters.

        Args:
            user_id: Telegram user ID for context
            **kwargs: Tool parameters as defined in parameters schema

        Returns:
            Tool execution result (will be serialized to JSON for LLM)
        """
        pass

    def to_openai_tool(self) -> dict[str, Any]:
        """
        Convert tool to OpenAI-compatible tool definition.

        Returns:
            Dict in OpenAI tool format
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __repr__(self) -> str:
        return f"<Tool: {self.name}>"
