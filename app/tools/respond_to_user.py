"""Tool: Respond to user with final message."""

from typing import Any

from app.tools.base import BaseTool


class RespondToUserTool(BaseTool):
    """Tool to send final response to user."""

    name = "respond_to_user"
    description = (
        "Send a response message to the user. "
        "ALWAYS use this tool to reply to the user. "
        "Do not respond with plain text - only through this tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "The message to send to the user (must be in Russian)",
            },
        },
        "required": ["response"],
    }

    async def execute(
        self,
        user_id: int,
        response: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the tool - just return the response for the handler to send.

        Args:
            user_id: Telegram user ID
            response: Response message for user

        Returns:
            Dictionary with response for handler
        """
        return {
            "type": "user_response",
            "response": response,
        }
