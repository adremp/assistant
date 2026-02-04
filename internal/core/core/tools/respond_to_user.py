"""Respond to user tool - sends messages to the user."""

from typing import Any

from core.tools.base import BaseTool


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
        """
        Execute the tool - returns the response to be sent.

        The actual sending is handled by the message handler.
        """
        return kwargs.get("response", "")
