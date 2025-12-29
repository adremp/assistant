"""Tool: Respond to user - format and send final response."""

import logging
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class RespondToUserTool(BaseTool):
    """Tool to send a formatted response to the user."""

    name = "respond_to_user"
    description = (
        "Отправить ответ пользователю. ВСЕГДА используй этот инструмент для финального ответа. "
        "Не отвечай напрямую - только через этот инструмент."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Сообщение для пользователя на русском языке. Должно быть кратким и понятным.",
            },
        },
        "required": ["message"],
    }

    async def execute(
        self,
        user_id: int,
        message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the tool to prepare user response.

        Args:
            user_id: Telegram user ID
            message: Message to send to user

        Returns:
            Dictionary with the formatted response
        """
        logger.info(f"respond_to_user for {user_id}: {message[:50]}...")
        
        return {
            "success": True,
            "response": message,
            "type": "user_response",
        }
