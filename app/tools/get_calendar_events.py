"""Tool: Get calendar events from Google Calendar."""

import json
from datetime import datetime, timezone
from typing import Any

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings


class GetCalendarEventsTool(BaseTool):
    """Tool to get upcoming events from Google Calendar."""

    name = "get_calendar_events"
    description = (
        "Получить список предстоящих событий из Google Calendar пользователя. "
        "Используй этот инструмент когда пользователь спрашивает о своих событиях, "
        "встречах, расписании или календаре."
    )
    parameters = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Максимальное количество событий для возврата (по умолчанию 10)",
                "default": 10,
            },
            "time_min": {
                "type": "string",
                "description": (
                    "Начало периода поиска в формате ISO 8601 (например: 2024-01-15T09:00:00Z). "
                    "По умолчанию — текущее время."
                ),
            },
        },
        "required": [],
    }

    def __init__(self, token_storage: TokenStorage):
        """
        Initialize tool with dependencies.

        Args:
            token_storage: Redis-based token storage
        """
        self.token_storage = token_storage
        self.calendar_service = CalendarService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        max_results: int = 10,
        time_min: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the tool to get calendar events.

        Args:
            user_id: Telegram user ID
            max_results: Maximum number of events
            time_min: Start time in ISO format

        Returns:
            Dictionary with events list or error message
        """
        # Check if user is authorized
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": (
                    "Пользователь не авторизован в Google. "
                    "Попроси пользователя выполнить команду /auth для авторизации."
                ),
            }

        try:
            events = await self.calendar_service.list_events(
                credentials=credentials,
                max_results=max_results,
                time_min=time_min,
            )

            if not events:
                return {
                    "success": True,
                    "events": [],
                    "message": "Нет предстоящих событий в календаре.",
                }

            return {
                "success": True,
                "events": events,
                "count": len(events),
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Ошибка при получении событий: {str(e)}",
            }
